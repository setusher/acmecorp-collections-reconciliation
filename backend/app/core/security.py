"""Auth tokens, input sanitisers and a tiny rate limiter."""
from __future__ import annotations

import hmac
import re
import time
from collections import defaultdict, deque

from email_validator import EmailNotValidError, validate_email
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

_HEADER_UNSAFE = re.compile(r"[\r\n\x00]")
_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_INVOICE_RE = re.compile(r"^INV-\d{3,6}$")
_CUSTOMER_RE = re.compile(r"^C\d{3,5}$")


class InputError(ValueError):
    pass


def normalize_email(value: str) -> str:
    if not isinstance(value, str) or _HEADER_UNSAFE.search(value) or len(value) > 254:
        raise InputError("invalid email address")
    try:
        return validate_email(value.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        raise InputError("invalid email address") from exc


def safe_header(value: str, max_len: int = 300) -> str:
    """Reject CR/LF (email header injection) and over-long values."""
    if not isinstance(value, str) or _HEADER_UNSAFE.search(value):
        raise InputError("header value must not contain line breaks")
    return value.strip()[:max_len]


def check_id(value: str) -> str:
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise InputError("invalid id")
    return value


def check_invoice_number(value: str) -> str:
    if not isinstance(value, str) or not _INVOICE_RE.match(value):
        raise InputError("invalid invoice number")
    return value


def check_customer_id(value: str) -> str:
    if not isinstance(value, str) or not _CUSTOMER_RE.match(value):
        raise InputError("invalid customer id")
    return value


def spreadsheet_safe(value: str) -> str:
    """Neutralise CSV/formula injection when exporting text to a spreadsheet."""
    if value and value[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


# ---------------------------------------------------------------- tokens
class TokenService:
    def __init__(self, secret: str, max_age_seconds: int):
        self._s = URLSafeTimedSerializer(secret, salt="acme-admin")
        self.max_age = max_age_seconds

    def issue(self, username: str) -> str:
        return self._s.dumps({"u": username})

    def verify(self, token: str) -> str | None:
        try:
            data = self._s.loads(token, max_age=self.max_age)
        except (BadSignature, SignatureExpired):
            return None
        return data.get("u") if isinstance(data, dict) else None


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# ---------------------------------------------------------------- rate limit
class RateLimiter:
    """Sliding-window limiter keyed by (bucket, client). In-memory: fine for one process."""

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def allow(self, bucket: str, client: str, limit: int, window_s: float) -> bool:
        now = time.monotonic()
        q = self._hits[(bucket, client)]
        while q and now - q[0] > window_s:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True
