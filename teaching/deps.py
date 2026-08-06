"""FastAPI auth dependencies."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, Header, HTTPException, status

from teaching.auth_store import AUTH_STORE
from teaching.rbac import is_admin, normalize_role


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    value = authorization.strip()
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return value or None


def get_optional_user(authorization: str | None = Header(default=None)) -> dict[str, Any] | None:
    token = _extract_bearer(authorization)
    user = AUTH_STORE.get_session_user(token)
    if user and (user.get("status") or "active") != "active":
        return None
    return user


def require_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    token = _extract_bearer(authorization)
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
