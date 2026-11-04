"""Security middlewares: JSON operator guard (NoSQL injection) and security headers."""
from __future__ import annotations

import json

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

MAX_JSON_BYTES = 256 * 1024


def has_mongo_operator(value, depth: int = 0) -> bool:
    if depth > 20:
        return True
    if isinstance(value, dict):
        return any(
            (isinstance(k, str) and (k.startswith("$") or "\x00" in k)) or has_mongo_operator(v, depth + 1)
            for k, v in value.items()
        )
    if isinstance(value, list):
        return any(has_mongo_operator(v, depth + 1) for v in value)
    return False


class JSONGuardMiddleware(BaseHTTPMiddleware):
    """Reject JSON bodies that contain Mongo operators like {"$ne": ...} anywhere.

    Pydantic models already refuse objects where strings are expected; this is defence in depth.
    """

    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH") and "application/json" in request.headers.get("content-type", ""):
            body = await request.body()
            if len(body) > MAX_JSON_BYTES:
                return JSONResponse({"error": {"code": "too_large", "message": "request body too large"}}, 413)
            if body:
                try:
                    data = json.loads(body)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    return JSONResponse({"error": {"code": "invalid_json", "message": "malformed JSON"}}, 400)
                if has_mongo_operator(data):
                    return JSONResponse({"error": {"code": "invalid_input",
                                                   "message": "operator keys are not allowed"}}, 400)
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        if not request.url.path.startswith(("/docs", "/redoc", "/openapi.json")):
            resp.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        resp.headers.setdefault("Cache-Control", "no-store")
        return resp
