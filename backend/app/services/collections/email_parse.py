"""Parse inbound RFC 822 mail into a safe, plain-text structure."""
from __future__ import annotations

import email
import html
import re
from dataclasses import dataclass, field
from email import policy
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from datetime import datetime, timezone

MAX_BODY_CHARS = 20000


@dataclass
class InboundEmail:
    message_id: str
    from_addr: str
    from_name: str
    to_addrs: list[str]
    subject: str
    date: datetime | None
    body_text: str
    in_reply_to: str | None = None
    references: list[str] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    content_type: str = "text/plain"


_ID_RE = re.compile(r"<[^<>\s]+>")


def _ids(value: str | None) -> list[str]:
    return _ID_RE.findall(value or "")


def html_to_text(markup: str) -> str:
    markup = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", markup)
    markup = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", markup)
    markup = re.sub(r"(?s)<[^>]+>", " ", markup)
    text = html.unescape(markup)
    return "\n".join(" ".join(line.split()) for line in text.splitlines()).strip()


def _body(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        content = part.get_content()
    except (LookupError, UnicodeDecodeError):
        payload = part.get_payload(decode=True) or b""
        content = payload.decode("utf-8", errors="replace")
    if part.get_content_type() == "text/html":
        content = html_to_text(content)
    return content.replace("\r\n", "\n")[:MAX_BODY_CHARS]


KEEP_HEADERS = ("auto-submitted", "x-autoreply", "x-autorespond", "precedence", "x-auto-response-suppress",
                "authentication-results", "return-path", "x-failed-recipients", "content-type")


def parse_email(raw: bytes) -> InboundEmail:
    msg: EmailMessage = email.message_from_bytes(raw, policy=policy.default)  # type: ignore[assignment]
    name, addr = parseaddr(str(msg.get("From", "")))
    try:
        dt = parsedate_to_datetime(str(msg["Date"])) if msg["Date"] else None
    except (TypeError, ValueError):
        dt = None
    mid = (_ids(str(msg.get("Message-ID", ""))) or [""])[0]
    headers = {h: str(msg.get(h)) for h in KEEP_HEADERS if msg.get(h) is not None}
    return InboundEmail(
        message_id=mid,
        from_addr=addr.strip().lower(),
        from_name=name.strip(),
        to_addrs=[a.lower() for _, a in getaddresses([str(v) for v in msg.get_all("To", [])])],
        subject=" ".join(str(msg.get("Subject", "")).split())[:300],
        date=dt.astimezone(timezone.utc) if dt and dt.tzinfo else dt,
        body_text=_body(msg),
        in_reply_to=(_ids(str(msg.get("In-Reply-To", ""))) or [None])[0],
        references=_ids(str(msg.get("References", ""))),
        headers=headers,
        content_type=msg.get_content_type(),
    )


_QUOTE_MARKERS = [
    re.compile(r"^On .{0,200}wrote:\s*$", re.IGNORECASE),
    re.compile(r"^-{2,}\s*Original Message\s*-{2,}", re.IGNORECASE),
    re.compile(r"^-{2,}\s*Forwarded message\s*-{2,}", re.IGNORECASE),
    re.compile(r"^From:\s.+", re.IGNORECASE),
    re.compile(r"^_{10,}$"),
    re.compile(r"^Sent from my (iPhone|Android|mobile)", re.IGNORECASE),
]
_SIG_MARKERS = [re.compile(r"^--\s*$")]


def strip_quoted(text: str) -> str:
    """Keep only the new part of a reply: drop quoted history and the signature."""
    out: list[str] = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Gmail sometimes wraps "On ... wrote:" over two lines.
        joined = f"{stripped} {lines[i + 1].strip()}" if i + 1 < len(lines) else stripped
        if any(p.match(stripped) for p in _QUOTE_MARKERS + _SIG_MARKERS) or (
            stripped.startswith("On ") and _QUOTE_MARKERS[0].match(joined)
        ):
            break
        if stripped.startswith(">"):
            continue
        out.append(line.rstrip())
    result = "\n".join(out).strip()
    return result or text.strip()[:2000]


_AUTO_SUBJECT = re.compile(
    r"^(auto(matic)?[\s-]*(reply|response)|out of (the )?office|ooo\b|away from|on leave|vacation|abwesenheit)",
    re.IGNORECASE,
)
_BOUNCE_SUBJECT = re.compile(
    r"(undeliver|delivery status notification|delivery (has )?failed|mail delivery (failed|subsystem)|"
    r"returned mail|failure notice|could not be delivered)",
    re.IGNORECASE,
)


def detect_automated(mail: InboundEmail) -> str | None:
    """Return 'bounce', 'auto_reply' or None."""
    h = {k.lower(): v.lower() for k, v in mail.headers.items()}
    local = mail.from_addr.split("@")[0]
    if (
        local in {"mailer-daemon", "postmaster"}
        or "x-failed-recipients" in h
        or ("multipart/report" in h.get("content-type", "") and "delivery-status" in h.get("content-type", ""))
        or mail.content_type == "multipart/report"
        or _BOUNCE_SUBJECT.search(mail.subject)
    ):
        return "bounce"
    if (
        h.get("auto-submitted", "no") not in ("", "no")
        or "x-autoreply" in h
        or "x-autorespond" in h
        or h.get("precedence", "") in ("auto_reply", "bulk", "junk")
        or _AUTO_SUBJECT.search(mail.subject)
    ):
        return "auto_reply"
    return None


def auth_failed(mail: InboundEmail) -> bool:
    """True when the receiving server recorded an SPF/DKIM/DMARC failure (possible spoofing)."""
    ar = mail.headers.get("authentication-results", "").lower()
    return any(tok in ar for tok in ("dmarc=fail", "spf=fail", "dkim=fail"))
