from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid


def make_email(from_addr: str, subject: str, body: str, to: str = "org@test.local", in_reply_to: str | None = None,
               headers: dict | None = None, html: bool = False) -> bytes:
    m = EmailMessage()
    m["From"] = from_addr
    m["To"] = to
    m["Subject"] = subject
    m["Date"] = format_datetime(datetime(2026, 11, 5, 10, 0, tzinfo=UTC))
    m["Message-ID"] = make_msgid(domain="customer.test")
    if in_reply_to:
        m["In-Reply-To"] = in_reply_to
        m["References"] = in_reply_to
    for k, v in (headers or {}).items():
        m[k] = v
    if html:
        m.set_content(body, subtype="html")
    else:
        m.set_content(body)
    return bytes(m)
