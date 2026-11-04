"""Outgoing mail via smtplib (run in a worker thread so the event loop never blocks)."""
from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from typing import Protocol

from app.core.config import Settings
from app.core.security import safe_header

log = logging.getLogger(__name__)


class MailError(RuntimeError):
    pass


@dataclass
class OutgoingMail:
    to: str
    subject: str
    body: str
    in_reply_to: str | None = None
    references: list[str] = field(default_factory=list)
    auto_submitted: str | None = None  # RFC 3834: "auto-generated" / "auto-replied"


class Mailer(Protocol):
    async def send(self, mail: OutgoingMail) -> str: ...


def build_message(mail: OutgoingMail, from_addr: str, from_name: str) -> EmailMessage:
    msg = EmailMessage()
    domain = from_addr.split("@")[-1] or "acmecorp.local"
    msg["Message-ID"] = make_msgid(idstring="acme", domain=domain)
    msg["Date"] = formatdate(localtime=False)
    msg["From"] = formataddr((safe_header(from_name), safe_header(from_addr)))
    msg["To"] = safe_header(mail.to)
    msg["Reply-To"] = safe_header(from_addr)
    msg["Subject"] = safe_header(mail.subject, 250)
    if mail.in_reply_to:
        msg["In-Reply-To"] = safe_header(mail.in_reply_to)
        refs = [safe_header(r) for r in mail.references if r]
        if mail.in_reply_to not in refs:
            refs.append(mail.in_reply_to)
        msg["References"] = " ".join(refs[-20:])
    if mail.auto_submitted:
        msg["Auto-Submitted"] = mail.auto_submitted
    msg.set_content(mail.body)
    return msg


class SMTPMailer:
    def __init__(self, settings: Settings, from_name: str = "AcmeCorp Accounts Team"):
        self.s = settings
        self.from_name = from_name

    def _send_sync(self, msg: EmailMessage) -> None:
        s = self.s
        ctx = ssl.create_default_context()
        if s.smtp_ssl:
            server: smtplib.SMTP = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, context=ctx, timeout=30)
        else:
            server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30)
        try:
            server.ehlo()
            if s.smtp_starttls and not s.smtp_ssl:
                server.starttls(context=ctx)
                server.ehlo()
            if s.smtp_username:
                server.login(s.smtp_username, s.smtp_password)
            server.send_message(msg)
        finally:
            try:
                server.quit()
            except smtplib.SMTPException:
                pass

    async def send(self, mail: OutgoingMail) -> str:
        if not self.s.email_configured:
            raise MailError("SMTP is not configured (set SMTP_HOST and ORG_EMAIL_ADDRESS)")
        msg = build_message(mail, self.s.org_email_address, self.from_name)
        try:
            await asyncio.to_thread(self._send_sync, msg)
        except (smtplib.SMTPException, OSError) as exc:
            log.warning("SMTP send failed: %s", type(exc).__name__)
            raise MailError(f"could not send email ({type(exc).__name__})") from exc
        return str(msg["Message-ID"])


class FakeMailer:
    """Collects messages instead of sending them (tests / dry runs)."""

    def __init__(self, from_addr: str = "accounts@acme.test"):
        self.from_addr = from_addr
        self.sent: list[EmailMessage] = []
        self.fail = False

    async def send(self, mail: OutgoingMail) -> str:
        if self.fail:
            raise MailError("fake failure")
        msg = build_message(mail, self.from_addr, "AcmeCorp Accounts Team")
        self.sent.append(msg)
        return str(msg["Message-ID"])
