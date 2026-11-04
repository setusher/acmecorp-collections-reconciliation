"""Optional developer endpoint (ENABLE_DEV_ENDPOINTS=true): inject an inbound email without a mailbox.

The message goes through exactly the same pipeline as IMAP mail (parse -> dedupe -> thread -> agent).
"""
from __future__ import annotations

from email.message import EmailMessage
from email.utils import format_datetime, make_msgid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator

from app.core import clock
from app.core.security import normalize_email, safe_header
from app.routes.deps import require_user
from app.services.collections.inbox import process_raw

router = APIRouter(prefix="/api/dev", tags=["dev"], dependencies=[Depends(require_user)])


class SimulatedEmail(BaseModel):
    from_addr: str = Field(max_length=254)
    subject: str = Field(default="Re: [AcmeCorp] Payment reminder", max_length=250)
    body: str = Field(min_length=1, max_length=10000)
    in_reply_to: str | None = Field(default=None, max_length=300)

    @field_validator("subject", "in_reply_to")
    @classmethod
    def no_crlf(cls, v: str | None) -> str | None:
        return safe_header(v) if v else v


@router.post("/simulate-inbound")
async def simulate_inbound(body: SimulatedEmail, request: Request) -> dict:
    st = request.app.state
    m = EmailMessage()
    m["From"] = normalize_email(body.from_addr)
    m["To"] = st.settings.org_email_address or "accounts@acmecorp.local"
    m["Subject"] = body.subject
    m["Date"] = format_datetime(clock.now())
    m["Message-ID"] = make_msgid(domain="simulated.local")
    if body.in_reply_to:
        m["In-Reply-To"] = body.in_reply_to
        m["References"] = body.in_reply_to
    m.set_content(body.body)
    async with st.inbox_lock:
        return await process_raw(st.repos, bytes(m), st.mailer, st.llm, st.settings)
