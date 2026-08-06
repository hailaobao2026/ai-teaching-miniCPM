"""Role / registration helpers aligned with ai-teaching-video-platform RBAC."""

from __future__ import annotations

from typing import Any


ROLES = {
    "STUDENT": "student",
    "TEACHER": "teacher",
    "ADMIN": "admin",
}

LEGACY_USER_ROLE = "user"
PUBLIC_REGISTER_ROLES = {ROLES["STUDENT"], ROLES["TEACHER"]}

GRADE_CODES = (
    "grade7",
    "grade8",
    "grade9",
    "grade10",
    "grade11",
    "grade12",
)
GRADE_CODE_SET = set(GRADE_CODES)

GRADE_LABELS = {
    "grade7": "初一",
    "grade8": "初二",
    "grade9": "初三",
    "grade10": "高一",
    "grade11": "高二",
    "grade12": "高三",
}


def normalize_role(role: Any) -> str:
    value = str(role or "").strip().lower()
    if not value or value == LEGACY_USER_ROLE:
        return ROLES["STUDENT"]
    if value in {ROLES["STUDENT"], ROLES["TEACHER"], ROLES["ADMIN"]}:
        return value
    return ROLES["STUDENT"]


def is_admin(user: dict[str, Any] | None) -> bool:
    return normalize_role((user or {}).get("role")) == ROLES["ADMIN"]


def is_teacher(user: dict[str, Any] | None) -> bool:
    return normalize_role((user or {}).get("role")) == ROLES["TEACHER"]


def is_student(user: dict[str, Any] | None) -> bool:
    return normalize_role((user or {}).get("role")) == ROLES["STUDENT"]


def public_user(user: dict[str, Any] | None) -> dict[str, Any] | None:
    if not user:
        return None
    return {
        "id": user.get("id"),
        "email": user.get("email"),
        "nickname": user.get("nickname"),
        "role": normalize_role(user.get("role")),
        "status": user.get("status") or "active",
        "grade": user.get("grade_code") or user.get("grade"),
        "created_at": user.get("created_at"),
    }


def validate_register_payload(body: dict[str, Any] | None) -> dict[str, Any]:
    body = body or {}
    email = str(body.get("email") or "").strip().lower()
    password = str(body.get("password") or "")
    nickname = str(body.get("nickname") or "").strip()
    role = str(body.get("role") or ROLES["STUDENT"]).strip().lower()
    grade = str(body.get("grade") or "").strip() or None

    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return {"ok": False, "error": "邮箱格式无效"}
    if len(password) < 8 or len(password) > 128:
        return {"ok": False, "error": "密码长度应为 8-128 位"}
    if not any(ch.isalpha() for ch in password) or not any(ch.isdigit() for ch in password):
        return {"ok": False, "error": "密码需同时包含字母和数字"}
    if len(nickname) < 2 or len(nickname) > 32:
        return {"ok": False, "error": "昵称长度应为 2-32 字"}
    if role == ROLES["ADMIN"]:
        return {"ok": False, "error": "不允许注册管理员账号"}
    if role not in PUBLIC_REGISTER_ROLES:
        return {"ok": False, "error": "角色无效，仅支持 student 或 teacher"}
    if grade and grade not in GRADE_CODE_SET:
        return {"ok": False, "error": "年级无效"}

    return {
        "ok": True,
        "value": {
            "email": email,
            "password": password,
            "nickname": nickname,
            "role": role,
            "grade": grade if role == ROLES["STUDENT"] else None,
        },
    }
