"""Sign-in routes for the personal desk. These stay outside the data gate."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from openjarvis.personal.gate import (
    apply_session_cookie,
    clear_failures,
    clear_session_cookie,
    cookie_token,
    issue_session,
    lockout_remaining,
    password_is_set,
    register_failure,
    request_unlocked,
    revoke_session,
    set_password,
    verify_password,
)

auth_router = APIRouter(prefix="/v1/personal/auth", tags=["personal-auth"])


class PasswordBody(BaseModel):
    password: str = Field(default="")


def _reject_if_locked_out(request: Request) -> None:
    remaining = lockout_remaining(request)
    if remaining:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Try again later.",
            headers={"Retry-After": str(remaining)},
        )


@auth_router.get("/status")
def auth_status(request: Request) -> dict[str, bool]:
    return {
        "password_set": password_is_set(),
        "unlocked": request_unlocked(request),
    }


@auth_router.post("/setup")
def auth_setup(body: PasswordBody, request: Request) -> JSONResponse:
    if password_is_set():
        raise HTTPException(status_code=409, detail="A password is already set.")
    _reject_if_locked_out(request)
    try:
        set_password(body.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    clear_failures(request)
    response = JSONResponse({"ok": True, "unlocked": True})
    apply_session_cookie(response, issue_session())
    return response


@auth_router.post("/login")
def auth_login(body: PasswordBody, request: Request) -> JSONResponse:
    if not password_is_set():
        raise HTTPException(status_code=409, detail="Create a password first.")
    _reject_if_locked_out(request)
    if not verify_password(body.password):
        register_failure(request)
        remaining = lockout_remaining(request)
        if remaining:
            raise HTTPException(
                status_code=429,
                detail="Too many attempts. Try again later.",
                headers={"Retry-After": str(remaining)},
            )
        raise HTTPException(status_code=401, detail="Wrong password.")
    clear_failures(request)
    response = JSONResponse({"ok": True, "unlocked": True})
    apply_session_cookie(response, issue_session())
    return response


@auth_router.post("/logout")
@auth_router.post("/lock")
def auth_lock(request: Request) -> JSONResponse:
    revoke_session(cookie_token(request))
    response = JSONResponse({"ok": True, "unlocked": False})
    clear_session_cookie(response)
    return response
