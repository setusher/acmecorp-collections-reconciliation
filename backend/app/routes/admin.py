from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from app.core import clock
from app.repositories import Repos
from app.routes.deps import rate_limit, repos, require_user, serialize
from app.services.seed_service import reset

router = APIRouter(prefix="/api", tags=["admin"])


class ResetIn(BaseModel):
    confirm: Literal["RESET"]  # server-side guard: the body must literally say RESET


@router.post("/admin/reset", dependencies=[rate_limit("reset", 5, 60)])
async def reset_demo(body: ResetIn, request: Request, r: Repos = Depends(repos),
                     user: str = Depends(require_user)) -> dict:
    async with request.app.state.inbox_lock:  # never reset in the middle of inbox processing
        result = await reset(r, request.app.state.settings, user)
    return {"ok": True, **result}


@router.get("/audit-log", dependencies=[Depends(require_user)])
async def audit_log(r: Repos = Depends(repos), limit: int = Query(default=200, ge=1, le=1000)) -> list[dict]:
    return [serialize(d) for d in await r.audit.list(limit)]


@router.get("/health")
async def health(request: Request) -> dict:
    try:
        await request.app.state.db.command("ping")
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    return {"ok": db_ok, "db": db_ok}


@router.get("/system/status", dependencies=[Depends(require_user)])
async def system_status(request: Request) -> dict:
    s = request.app.state.settings
    return {
        "today": clock.today().isoformat(),
        "as_of_date_pinned": bool(s.app_as_of_date),
        "smtp_configured": s.email_configured,
        "imap_configured": s.imap_configured,
        "org_email": s.org_email_address,
        "llm_provider": request.app.state.llm.name,
        "inbox_poll_seconds": s.inbox_poll_seconds if s.imap_configured else 0,
        "reminder_interval_days": s.reminder_interval_days,
        "reminder_schedule_minutes": s.reminder_schedule_minutes,
        "last_inbox_poll": request.app.state.last_inbox_poll,
    }
