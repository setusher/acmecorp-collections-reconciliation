"""FastAPI application factory and background jobs."""
from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.middleware import JSONGuardMiddleware, SecurityHeadersMiddleware
from app.core.security import RateLimiter, TokenService
from app.integrations.imap import IMAPInbox, InboxError
from app.integrations.llm import build_llm
from app.integrations.smtp import FakeMailer, SMTPMailer
from app.repositories import Repos
from app.repositories.db import connect, ensure_indexes
from app.routes import admin, auth, collections, dev, master, reconciliation

log = logging.getLogger("acmecorp")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


async def _inbox_loop(app: FastAPI) -> None:
    st = app.state
    while True:
        await asyncio.sleep(st.settings.inbox_poll_seconds)
        try:
            res = await collections.run_inbox(st)
            if res["fetched"]:
                log.info("inbox poll processed %s message(s)", res["fetched"])
        except InboxError as exc:
            log.warning("inbox poll failed: %s", exc)
        except Exception:
            log.exception("inbox poll crashed; will retry")


async def _reminder_loop(app: FastAPI) -> None:
    from app.services.collections.reminders import send_reminders

    st = app.state
    while True:
        await asyncio.sleep(st.settings.reminder_schedule_minutes * 60)
        try:
            res = await send_reminders(st.repos, st.mailer, st.settings, "scheduler", scheduled=True)
            log.info("scheduled reminders: sent=%s skipped=%s", len(res["sent"]), len(res["skipped"]))
        except Exception:
            log.exception("scheduled reminder run failed")


def create_app(settings: Settings | None = None, *, db=None, mailer=None, inbox=None, llm=None,
               start_background: bool = True) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = None
        if app.state.db is None:
            client, app.state.db = connect(settings)
        app.state.repos = Repos.from_db(app.state.db)
        try:
            await ensure_indexes(app.state.db)
        except Exception as exc:  # noqa: BLE001
            log.error("could not reach MongoDB (%s); is it running?", type(exc).__name__)
        if settings.admin_password in ("change-me", "") or settings.secret_key.startswith("dev-insecure"):
            log.warning("ADMIN_PASSWORD/SECRET_KEY are defaults: set them in .env before exposing this server")
        tasks = []
        if start_background and settings.imap_configured and settings.inbox_poll_seconds > 0:
            tasks.append(asyncio.create_task(_inbox_loop(app)))
        if start_background and settings.reminder_schedule_minutes > 0:
            tasks.append(asyncio.create_task(_reminder_loop(app)))
        yield
        for t in tasks:
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await t
        if client:
            client.close()

    app = FastAPI(title="AcmeCorp Collections & Reconciliation API", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.db = db
    app.state.repos = Repos.from_db(db) if db is not None else None
    if mailer is None:
        mailer = FakeMailer(settings.org_email_address or "accounts@acmecorp.local") \
            if settings.mail_transport == "log" else SMTPMailer(settings)
    app.state.mailer = mailer
    app.state.inbox = inbox or IMAPInbox(settings)
    app.state.llm = llm or build_llm(settings)
    app.state.tokens = TokenService(settings.secret_key, settings.session_hours * 3600)
    app.state.rate_limiter = RateLimiter()
    app.state.inbox_lock = asyncio.Lock()
    app.state.last_inbox_poll = None

    app.add_middleware(JSONGuardMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.frontend_origin.split(",") if o.strip()],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Authorization", "Content-Type"],
    )
    install_error_handlers(app)
    for r in (auth.router, admin.router, master.router, collections.router, reconciliation.router):
        app.include_router(r)
    if settings.enable_dev_endpoints:
        app.include_router(dev.router)
    return app


app = create_app()
