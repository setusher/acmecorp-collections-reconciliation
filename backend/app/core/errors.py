"""Consistent JSON errors; never leak stack traces."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.security import InputError
from app.integrations.imap import InboxError
from app.integrations.smtp import MailError
from app.services.reconciliation import ConflictError, ReconciliationError

log = logging.getLogger(__name__)


def _err(status: int, code: str, message: str, details=None) -> JSONResponse:
    body = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(status_code=status, content=body)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exc(_: Request, exc: StarletteHTTPException):
        return _err(exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_exc(_: Request, exc: RequestValidationError):
        details = [{"loc": [str(x) for x in e.get("loc", [])], "msg": e.get("msg")} for e in exc.errors()][:20]
        return _err(422, "validation_error", "request validation failed", details)

    @app.exception_handler(InputError)
    async def input_exc(_: Request, exc: InputError):
        return _err(400, "invalid_input", str(exc))

    @app.exception_handler(ReconciliationError)
    async def recon_exc(_: Request, exc: ReconciliationError):
        return _err(400, "reconciliation_error", str(exc))

    @app.exception_handler(ConflictError)
    async def conflict_exc(_: Request, exc: ConflictError):
        return _err(409, "conflict", str(exc))

    @app.exception_handler(LookupError)
    async def notfound_exc(_: Request, exc: LookupError):
        return _err(404, "not_found", str(exc).strip("'\""))

    @app.exception_handler(MailError)
    async def mail_exc(_: Request, exc: MailError):
        return _err(502, "mail_error", str(exc))

    @app.exception_handler(InboxError)
    async def inbox_exc(_: Request, exc: InboxError):
        return _err(502, "inbox_error", str(exc))

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("unhandled error: %s", type(exc).__name__)
        return _err(500, "internal_error", "internal server error")
