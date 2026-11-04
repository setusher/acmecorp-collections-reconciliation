"""Shared route dependencies."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from app.repositories import Repos


def get_state(request: Request):
    return request.app.state


def repos(request: Request) -> Repos:
    return request.app.state.repos


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def require_user(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    user = request.app.state.tokens.verify(token) if token else None
    if not user:
        raise HTTPException(status_code=401, detail="authentication required")
    return user


def rate_limit(bucket: str, limit: int, window_s: float):
    def dep(request: Request) -> None:
        key = client_ip(request)
        if not request.app.state.rate_limiter.allow(bucket, key, limit, window_s):
            raise HTTPException(status_code=429, detail=f"too many requests to {bucket}; try again shortly")
    return Depends(dep)


def serialize(doc: dict | None) -> dict | None:
    """Mongo doc -> JSON-friendly dict with ``id`` instead of ``_id``."""
    if doc is None:
        return None
    out = {("id" if k == "_id" else k): v for k, v in doc.items()}
    return out
