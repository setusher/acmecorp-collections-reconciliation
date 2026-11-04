from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.security import constant_time_equals
from app.routes.deps import rate_limit

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class LoginOut(BaseModel):
    token: str
    username: str
    expires_in_seconds: int


@router.post("/login", response_model=LoginOut, dependencies=[rate_limit("login", 10, 60)])
async def login(body: LoginIn, request: Request) -> LoginOut:
    s = request.app.state.settings
    ok_user = constant_time_equals(body.username, s.admin_username)
    ok_pass = constant_time_equals(body.password, s.admin_password)
    if not (ok_user and ok_pass):
        raise HTTPException(status_code=401, detail="invalid username or password")
    tokens = request.app.state.tokens
    return LoginOut(token=tokens.issue(body.username), username=body.username, expires_in_seconds=tokens.max_age)
