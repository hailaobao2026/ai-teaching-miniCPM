"""FastAPI auth dependencies (Bearer header or HttpOnly session cookie)."""

from __future__ import annotations

import os
from typing import Any, Callable

from fastapi import Depends, Header, HTTPException, Request, status

from teaching.auth_store import AUTH_STORE
from teaching.rbac import is_admin, normalize_role

COOKIE_NAME = os.getenv("MATH_COACH_COOKIE_NAME", "math_coach_token")


def cookie_name() -> str:
    return os.getenv("MATH_COACH_COOKIE_NAME", "math_coach_token") or "math_coach_token"


def cookie_secure() -> bool:
    raw = (os.getenv("MATH_COACH_COOKIE_SECURE") or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    # Auto: secure when explicitly behind HTTPS proxy or production-ish flag.
    return (os.getenv("HTTPS") or "").lower() in {"1", "true", "on"}


def cookie_samesite() -> str:
    value = (os.getenv("MATH_COACH_COOKIE_SAMESITE") or "lax").strip().lower()
    if value not in {"lax", "strict", "none"}:
        return "lax"
    return value


def session_ttl_seconds() -> int:
    raw = os.getenv("MATH_COACH_SESSION_TTL_SECONDS", "").strip()
    if raw.isdigit():
        return max(60, int(raw))
    from teaching.auth_store import SESSION_TTL_SECONDS

    return SESSION_TTL_SECONDS


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    value = authorization.strip()
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return value or None


def extract_token(
    request: Request | None = None,
    authorization: str | None = None,
) -> str | None:
    """Prefer Authorization Bearer, fall back to HttpOnly session cookie."""
    token = _extract_bearer(authorization)
    if token:
        return token
    if request is not None:
        cookie_token = request.cookies.get(cookie_name())
        if cookie_token:
            return cookie_token.strip() or None
    return None


def get_optional_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any] | None:
    token = extract_token(request, authorization)
    user = AUTH_STORE.get_session_user(token)
    if user and (user.get("status") or "active") != "active":
        return None
    return user


def require_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    token = extract_token(request, authorization)
    user = AUTH_STORE.get_session_user(token)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    if (user.get("status") or "active") != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号已禁用")
    return user


def require_roles(*roles: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    allowed = {normalize_role(role) for role in roles}

    def _dep(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        if normalize_role(user.get("role")) not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")
        return user

    return _dep


def require_admin(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    if not is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员")
    return user
