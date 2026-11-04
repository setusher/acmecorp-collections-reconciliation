"""Collections agent: reminders, inbox, conversations, Needs attention."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from app.core import clock
from app.core.security import check_id, safe_header
from app.repositories import Repos
from app.routes.deps import rate_limit, repos, require_user, serialize
from app.services.collections.inbox import process_inbox, resolve_conversation, send_human_reply
from app.services.collections.reminders import send_reminders

router = APIRouter(prefix="/api", tags=["collections"], dependencies=[Depends(require_user)])


class SendRemindersIn(BaseModel):
    force: bool = False  # ignore REMINDER_INTERVAL_DAYS for this manual run (audit-logged)


@router.post("/collections/send-reminders", dependencies=[rate_limit("reminders", 6, 60)])
async def post_send_reminders(request: Request, body: SendRemindersIn | None = None, r: Repos = Depends(repos),
                              user: str = Depends(require_user)):
    st = request.app.state
    return await send_reminders(r, st.mailer, st.settings, user, force=bool(body and body.force))


async def run_inbox(state) -> dict:
    async with state.inbox_lock:
        result = await process_inbox(state.repos, state.inbox, state.mailer, state.llm, state.settings)
        state.last_inbox_poll = clock.now().isoformat()
        return result


@router.post("/collections/check-inbox", dependencies=[rate_limit("inbox", 6, 60)])
async def post_check_inbox(request: Request) -> dict:
    return await run_inbox(request.app.state)


async def _customer_names(r: Repos) -> dict[str, str]:
    return {c.customer_id: c.name for c in await r.master.list_customers()}


@router.get("/conversations")
async def list_conversations(r: Repos = Depends(repos),
                             status: str | None = Query(default=None, pattern="^(open|needs_attention|resolved)$"),
                             customer_id: str | None = Query(default=None, pattern=r"^C\d{3,5}$")) -> list[dict]:
    names = await _customer_names(r)
    out = []
    for c in await r.collections.list_conversations(status, customer_id):
        msgs = await r.collections.list_messages(c["_id"])
        last = msgs[-1] if msgs else None
        out.append({**serialize(c), "customer_name": names.get(c.get("customer_id") or "", None),
                    "message_count": len(msgs),
                    "last_message": {"direction": last["direction"], "kind": last.get("kind"),
                                     "category": last.get("category"), "at": last["created_at"],
                                     "subject": last.get("subject")} if last else None})
    return out


@router.get("/conversations/{conv_id}")
async def get_conversation(conv_id: str, r: Repos = Depends(repos)) -> dict:
    conv = await r.collections.get_conversation(check_id(conv_id))
    if conv is None:
        raise HTTPException(404, "conversation not found")
    names = await _customer_names(r)
    customer = await r.master.get_customer(conv["customer_id"]) if conv.get("customer_id") else None
    return {**serialize(conv), "customer_name": names.get(conv.get("customer_id") or ""),
            "customer_email": customer.contact_email if customer else None,
            "messages": [serialize(m) for m in await r.collections.list_messages(conv["_id"])]}


@router.get("/collections/needs-attention")
async def needs_attention(r: Repos = Depends(repos)) -> list[dict]:
    names = await _customer_names(r)
    out = []
    for conv in await r.collections.list_conversations("needs_attention"):
        msgs = await r.collections.list_messages(conv["_id"])
        flagged = [m for m in msgs if m.get("needs_attention")]
        msg = flagged[-1] if flagged else (msgs[-1] if msgs else None)
        out.append({"conversation_id": conv["_id"], "customer_id": conv.get("customer_id"),
                    "customer_name": names.get(conv.get("customer_id") or ""),
                    "reason": (msg or {}).get("reason") or conv.get("attention_reason"),
                    "message": serialize(msg), "updated_at": conv["updated_at"]})
    return out


class ReplyIn(BaseModel):
    body: str = Field(min_length=1, max_length=10000)
    subject: str | None = Field(default=None, max_length=250)

    @field_validator("subject")
    @classmethod
    def no_crlf(cls, v: str | None) -> str | None:
        return safe_header(v) if v else v


@router.post("/conversations/{conv_id}/reply")
async def post_reply(conv_id: str, body: ReplyIn, request: Request, r: Repos = Depends(repos),
                     user: str = Depends(require_user)) -> dict:
    return await send_human_reply(r, request.app.state.mailer, check_id(conv_id), body.body, user, body.subject)


class ResolveIn(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


@router.post("/conversations/{conv_id}/resolve")
async def post_resolve(conv_id: str, body: ResolveIn, r: Repos = Depends(repos),
                       user: str = Depends(require_user)) -> dict:
    await resolve_conversation(r, check_id(conv_id), user, body.note)
    return {"ok": True}
