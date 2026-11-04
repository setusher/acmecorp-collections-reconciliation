"""Single source of "today".

Everything that depends on the current date (overdue status, reminder cadence,
date plausibility in matching) calls :func:`today`. Setting ``APP_AS_OF_DATE``
(YYYY-MM-DD) pins the date so behaviour is deterministic in demos and tests.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone


def today() -> date:
    raw = (os.environ.get("APP_AS_OF_DATE") or "").strip()
    if not raw:
        from app.core.config import get_settings

        raw = (get_settings().app_as_of_date or "").strip()
    if raw:
        return date.fromisoformat(raw)
    return date.today()


def now() -> datetime:
    """Current UTC timestamp (used for audit trails; not affected by APP_AS_OF_DATE)."""
    return datetime.now(timezone.utc)
