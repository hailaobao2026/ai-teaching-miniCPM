"""User/session store with SQLite and MySQL backends.

Environment:
  MATH_COACH_DB_BACKEND = sqlite | mysql   (default: sqlite)
  MATH_COACH_SQLITE_PATH = data/math-coach.db
  MATH_COACH_MYSQL_HOST / PORT / USER / PASSWORD / DATABASE
  MATH_COACH_MYSQL_DSN = mysql+pymysql://user:pass@host:3306/db  (optional override)
  MATH_COACH_AUTH_DB = legacy JSON path; if set and backend unset, falls back to
                       sqlite file derived from the same data directory.
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
import time
import uuid
from datetime import datetime, timezone
from hashlib import sha256
from hashlib import scrypt
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote_plus

from teaching.runtime_env import load_runtime_env
from teaching.rbac import ROLES, normalize_role, public_user

load_runtime_env()

SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
_LOCK = threading.RLock()


_SCRYPT_N = int(os.getenv("MATH_COACH_SCRYPT_N", str(2**12)))


class NotebookConflictError(ValueError):
    """The notebook item cannot transition because another writer changed it."""


def _password_looks_weak(password: str) -> bool:
    """Reject empty/short/common demo passwords used historically in this repo."""
    value = str(password or "")
    if len(value) < 8:
        return True
    lowered = value.lower()
    banned = {
        "demo123",
        "password",
        "password1",
        "12345678",
        "mathcoach",
        "rootpass",
        "admin123",
        "changeme",
    }
    if lowered in banned:
        return True
    if not any(ch.isalpha() for ch in value) or not any(ch.isdigit() for ch in value):
        return True
    return False


def require_strong_password(password: str, *, label: str) -> str:
    value = str(password or "")
    if not value.strip():
        raise RuntimeError(
            f"{label} is required and must be a strong password "
            "(set via environment; no hardcoded fallback)."
        )
    if _password_looks_weak(value):
        raise RuntimeError(
            f"{label} is too weak. Use at least 8 characters and avoid common "
            "defaults such as demo123 / password / mathcoach."
        )
    return value


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _utc_now_iso() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")


def _generate_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _session_token_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = scrypt(
        str(password).encode("utf-8"),
        salt=bytes.fromhex(salt),
        n=_SCRYPT_N,
        r=8,
        p=1,
        dklen=32,
    ).hex()
    return f"scrypt${salt}${digest}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded or not encoded.startswith("scrypt$"):
        return False
    try:
        _, salt, expected_hex = encoded.split("$", 2)
    except ValueError:
        return False
    # Accept both historical n=2**12 and n=2**14 hashes by re-deriving with
    # the n embedded implicitly via verification against stored digest only
    # when using the active parameter set. For compatibility, try active n
    # first, then fall back to 2**14.
    for n in {_SCRYPT_N, 2**12, 2**14}:
        actual = scrypt(
            str(password).encode("utf-8"),
            salt=bytes.fromhex(salt),
            n=n,
            r=8,
            p=1,
            dklen=32,
        )
        expected = bytes.fromhex(expected_hex)
        if secrets.compare_digest(actual, expected):
            return True
    return False


def resolve_backend() -> str:
    raw = (os.getenv("MATH_COACH_DB_BACKEND") or "").strip().lower()
    if raw in {"sqlite", "mysql"}:
        return raw
    # Backward-compatible default.
    return "sqlite"


def resolve_database_url() -> str:
    backend = resolve_backend()
    if backend == "mysql":
        dsn = (os.getenv("MATH_COACH_MYSQL_DSN") or "").strip()
        if dsn:
            if dsn.startswith("mysql://"):
                dsn = "mysql+pymysql://" + dsn[len("mysql://") :]
            return dsn
        host = os.getenv("MATH_COACH_MYSQL_HOST", "127.0.0.1")
        port = os.getenv("MATH_COACH_MYSQL_PORT", "3306")
        user = os.getenv("MATH_COACH_MYSQL_USER", "mathcoach")
        password = (os.getenv("MATH_COACH_MYSQL_PASSWORD") or "").strip()
        if not password:
            raise RuntimeError(
                "MATH_COACH_MYSQL_PASSWORD must be set to a strong custom password "
                "when MATH_COACH_DB_BACKEND=mysql (no default password)."
            )
        database = os.getenv("MATH_COACH_MYSQL_DATABASE", "mathcoach")
        return (
            f"mysql+pymysql://{quote_plus(user)}:{quote_plus(password)}"
            f"@{host}:{port}/{database}?charset=utf8mb4"
        )

    # sqlite
    legacy_json = os.getenv("MATH_COACH_AUTH_DB", "").strip()
    sqlite_path = os.getenv("MATH_COACH_SQLITE_PATH", "").strip()
    if not sqlite_path:
        if legacy_json:
            sqlite_path = str(Path(legacy_json).with_name("math-coach.db"))
        else:
            sqlite_path = str(Path(__file__).resolve().parent.parent / "data" / "math-coach.db")
    path = Path(sqlite_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.resolve()}"


class AuthStore:
    """SQLAlchemy-backed users + sessions store."""

    def __init__(self, database_url: str | None = None) -> None:
        from sqlalchemy import (
            Column,
            DateTime,
            Integer,
            MetaData,
            String,
            Table,
            create_engine,
            delete,
            func,
            insert,
            select,
            text,
            update,
        )
        from sqlalchemy.engine import Engine
        from sqlalchemy.exc import IntegrityError

        self._sa = {
            "Column": Column,
            "DateTime": DateTime,
            "Integer": Integer,
            "MetaData": MetaData,
            "String": String,
            "Table": Table,
            "create_engine": create_engine,
            "delete": delete,
            "func": func,
            "insert": insert,
            "select": select,
            "text": text,
            "update": update,
            "IntegrityError": IntegrityError,
        }
        self.database_url = database_url or resolve_database_url()
        self.backend = "mysql" if self.database_url.startswith("mysql") else "sqlite"
        self.engine: Engine = self._make_engine(self.database_url)
        self.metadata = MetaData()
        self.users = Table(
            "users",
            self.metadata,
            Column("id", String(64), primary_key=True),
            Column("email", String(128), nullable=False, unique=True),
            Column("password_hash", String(255), nullable=False),
            Column("nickname", String(64), nullable=False),
            Column("role", String(16), nullable=False, default="student"),
            Column("status", String(16), nullable=False, default="active"),
            Column("grade_code", String(32), nullable=True),
            Column("created_at", DateTime(timezone=True), nullable=False),
        )
        self.sessions = Table(
            "sessions",
            self.metadata,
            Column("token", String(128), primary_key=True),
            Column("user_id", String(64), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
        )
        self.notebook_items = Table(
            "notebook_items",
            self.metadata,
            Column("id", String(64), primary_key=True),
            Column("user_id", String(64), nullable=False, index=True),
            Column("problem", String(4000), nullable=False),
            Column("topic", String(32), nullable=False, default="general"),
            Column("helpful", String(8), nullable=False, default="0"),
            Column("note", String(500), nullable=False, default=""),
            Column("stage", String(32), nullable=True),
            Column("final_answer", String(500), nullable=True),
            Column("reply", String(4000), nullable=True),
            Column("created_at", DateTime(timezone=True), nullable=False),
        )
        self.notebook_attempts = Table(
            "notebook_attempts",
            self.metadata,
            Column("id", String(64), primary_key=True),
            Column("notebook_item_id", String(64), nullable=False, index=True),
            Column("user_id", String(64), nullable=False, index=True),
            Column("attempt_number", Integer, nullable=False),
            Column("answer", String(500), nullable=False),
            Column("correct", String(8), nullable=False),
            Column("hint_level", Integer, nullable=False, default=0),
            Column("created_at", DateTime(timezone=True), nullable=False),
        )
        self._init_schema()
        self.ensure_seed_accounts()

    def _make_engine(self, url: str):
        create_engine = self._sa["create_engine"]
        if url.startswith("sqlite"):
            return create_engine(
                url,
                future=True,
                connect_args={"check_same_thread": False},
                pool_pre_ping=True,
            )
        return create_engine(url, future=True, pool_pre_ping=True, pool_recycle=3600)

    def _init_schema(self) -> None:
        text = self._sa["text"]
        # Ensure MySQL database exists when using discrete host settings.
        if self.backend == "mysql" and not (os.getenv("MATH_COACH_MYSQL_DSN") or "").strip():
            database = os.getenv("MATH_COACH_MYSQL_DATABASE", "mathcoach")
            # Connect without database first if possible.
            root_url = self.database_url.rsplit("/", 1)[0] + "/"
            try:
                bootstrap = self._make_engine(root_url)
                with bootstrap.begin() as conn:
                    conn.execute(
                        text(
                            f"CREATE DATABASE IF NOT EXISTS `{database}` "
                            "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                        )
                    )
                bootstrap.dispose()
            except Exception:
                # User may only have rights inside the target database.
                pass
        self.metadata.create_all(self.engine)
        # Light migration for legacy role values.
        with self.engine.begin() as conn:
            conn.execute(
                self._sa["text"](
                    "UPDATE users SET role='student' WHERE role IS NULL OR role='' OR role='user'"
                )
            )

    def _row_to_user(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        mapping = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
        created = mapping.get("created_at")
        if isinstance(created, datetime):
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            created_at = created.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        else:
            created_at = created
        return {
            "id": mapping.get("id"),
            "email": mapping.get("email"),
            "password_hash": mapping.get("password_hash"),
            "nickname": mapping.get("nickname"),
            "role": normalize_role(mapping.get("role")),
            "status": mapping.get("status") or "active",
            "grade_code": mapping.get("grade_code"),
            "created_at": created_at,
        }

    def ensure_seed_accounts(self) -> None:
        with _LOCK:
            # Default false: production-safe. Explicitly set SEED_DEMO_ACCOUNTS=true
            # and provide DEMO_*_PASSWORD for local demos.
            seed = str(os.getenv("SEED_DEMO_ACCOUNTS", "false")).lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            admin_email = (os.getenv("ADMIN_EMAIL") or "admin@example.com").strip().lower()
            admin_nickname = os.getenv("ADMIN_NICKNAME") or "系统管理员"
            admin = self.find_user_by_email(admin_email)
            if not admin:
                raw_admin_password = os.getenv("ADMIN_PASSWORD")
                if raw_admin_password is None or not str(raw_admin_password).strip():
                    # No admin yet and no password provided: skip auto-seed so
                    # deployments cannot silently boot with demo123.
                    logging.getLogger(__name__).warning(
                        "ADMIN_PASSWORD is not set; skipping initial admin seed. "
                        "Set ADMIN_EMAIL/ADMIN_PASSWORD to create the first admin."
                    )
                else:
                    admin_password = require_strong_password(
                        raw_admin_password, label="ADMIN_PASSWORD"
                    )
                    self._insert_user(
                        {
                            "id": _generate_id("user"),
                            "email": admin_email,
                            "password_hash": hash_password(admin_password),
                            "nickname": admin_nickname,
                            "role": ROLES["ADMIN"],
                            "status": "active",
                            "grade_code": None,
                            "created_at": _utc_now(),
                        }
                    )
            elif seed and normalize_role(admin.get("role")) != ROLES["ADMIN"]:
                self.update_user_admin(admin["id"], role=ROLES["ADMIN"], status="active")

            if not seed:
                return

            teacher_email = (
                os.getenv("DEMO_TEACHER_EMAIL") or "math.teacher@example.local"
            ).strip().lower()
            if not self.find_user_by_email(teacher_email):
                teacher_password = require_strong_password(
                    os.getenv("DEMO_TEACHER_PASSWORD") or "",
                    label="DEMO_TEACHER_PASSWORD",
                )
                self._insert_user(
                    {
                        "id": _generate_id("user"),
                        "email": teacher_email,
                        "password_hash": hash_password(teacher_password),
                        "nickname": os.getenv("DEMO_TEACHER_NICKNAME") or "数学老师",
                        "role": ROLES["TEACHER"],
                        "status": "active",
                        "grade_code": None,
                        "created_at": _utc_now(),
                    }
                )

            student_email = (
                os.getenv("DEMO_STUDENT_EMAIL") or "student@example.local"
            ).strip().lower()
            if not self.find_user_by_email(student_email):
                student_password = require_strong_password(
                    os.getenv("DEMO_STUDENT_PASSWORD") or "",
                    label="DEMO_STUDENT_PASSWORD",
                )
                self._insert_user(
                    {
                        "id": _generate_id("user"),
                        "email": student_email,
                        "password_hash": hash_password(student_password),
                        "nickname": os.getenv("DEMO_STUDENT_NICKNAME") or "演示学生",
                        "role": ROLES["STUDENT"],
                        "status": "active",
                        "grade_code": os.getenv("DEMO_STUDENT_GRADE") or "grade8",
                        "created_at": _utc_now(),
                    }
                )

    def _insert_user(self, user: dict[str, Any]) -> dict[str, Any]:
        insert = self._sa["insert"]
        with self.engine.begin() as conn:
            conn.execute(insert(self.users).values(**user))
        return self.find_user_by_id(user["id"]) or user

    def find_user_by_email(self, email: str) -> dict[str, Any] | None:
        select = self._sa["select"]
        email = str(email or "").strip().lower()
        with self.engine.begin() as conn:
            row = conn.execute(select(self.users).where(self.users.c.email == email)).first()
        return self._row_to_user(row)

    def find_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        select = self._sa["select"]
        with self.engine.begin() as conn:
            row = conn.execute(select(self.users).where(self.users.c.id == user_id)).first()
        return self._row_to_user(row)

    def create_user(
        self,
        *,
        email: str,
        password: str,
        nickname: str,
        role: str = ROLES["STUDENT"],
        grade: str | None = None,
    ) -> dict[str, Any]:
        normalized_role = normalize_role(role)
        if normalized_role == ROLES["ADMIN"]:
            raise ValueError("不允许通过注册创建管理员")
        email = str(email).strip().lower()
        user = {
            "id": _generate_id("user"),
            "email": email,
            "password_hash": hash_password(password),
            "nickname": nickname,
            "role": normalized_role,
            "status": "active",
            "grade_code": grade if normalized_role == ROLES["STUDENT"] else None,
            "created_at": _utc_now(),
        }
        try:
            created = self._insert_user(user)
        except self._sa["IntegrityError"] as exc:
            raise ValueError("邮箱已注册") from exc
        return created

    def create_session(self, user_id: str) -> str:
        insert = self._sa["insert"]
        token = secrets.token_urlsafe(32)
        with self.engine.begin() as conn:
            conn.execute(
                insert(self.sessions).values(
                    token=_session_token_hash(token),
                    user_id=user_id,
                    created_at=_utc_now(),
                )
            )
        return token

    def get_session_user(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        select = self._sa["select"]
        delete = self._sa["delete"]
        with self.engine.begin() as conn:
            token_hash = _session_token_hash(token)
            row = conn.execute(select(self.sessions).where(self.sessions.c.token == token_hash)).first()
            if not row:
                return None
            mapping = dict(row._mapping)
            created = mapping.get("created_at")
            if isinstance(created, datetime):
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                created_ts = created.timestamp()
            else:
                try:
                    created_ts = datetime.fromisoformat(str(created).replace("Z", "+00:00")).timestamp()
                except ValueError:
                    created_ts = 0
            if time.time() - created_ts > SESSION_TTL_SECONDS:
                conn.execute(delete(self.sessions).where(self.sessions.c.token == token_hash))
                return None
            user_row = conn.execute(
                select(self.users).where(self.users.c.id == mapping.get("user_id"))
            ).first()
        return self._row_to_user(user_row)

    def delete_session(self, token: str | None) -> None:
        if not token:
            return
        delete = self._sa["delete"]
        with self.engine.begin() as conn:
            conn.execute(delete(self.sessions).where(self.sessions.c.token == _session_token_hash(token)))

    def delete_sessions_for_user(self, user_id: str) -> None:
        delete = self._sa["delete"]
        with self.engine.begin() as conn:
            conn.execute(delete(self.sessions).where(self.sessions.c.user_id == user_id))

    def update_profile(
        self,
        user_id: str,
        *,
        nickname: str | None = None,
        grade: str | None = None,
    ) -> dict[str, Any]:
        user = self.find_user_by_id(user_id)
        if not user:
            raise ValueError("用户不存在")
        values: dict[str, Any] = {}
        if nickname is not None:
            nickname = str(nickname).strip()
            if len(nickname) < 2 or len(nickname) > 32:
                raise ValueError("昵称长度应为 2-32 字")
            values["nickname"] = nickname
        if grade is not None and normalize_role(user.get("role")) == ROLES["STUDENT"]:
            values["grade_code"] = grade or None
        if values:
            update = self._sa["update"]
            with self.engine.begin() as conn:
                conn.execute(update(self.users).where(self.users.c.id == user_id).values(**values))
        updated = self.find_user_by_id(user_id)
        if not updated:
            raise ValueError("用户不存在")
        return updated

    def list_users(
        self,
        *,
        role: str | None = None,
        status: str | None = None,
        query: str | None = None,
        page: int = 1,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        select = self._sa["select"]
        stmt = select(self.users)
        if role:
            stmt = stmt.where(self.users.c.role == normalize_role(role))
        if status:
            stmt = stmt.where(self.users.c.status == status)
        if query:
            q = f"%{query.strip().lower()}%"
            stmt = stmt.where(
                (self.users.c.email.like(q)) | (self.users.c.nickname.like(q))
            )
        page = max(1, int(page or 1))
        limit = max(1, min(200, int(limit or 50)))
        stmt = stmt.order_by(self.users.c.created_at.desc()).offset((page - 1) * limit).limit(limit)
        with self.engine.begin() as conn:
            rows = conn.execute(stmt).fetchall()
        users = [self._row_to_user(row) for row in rows]
        return [public_user(u) for u in users if u and public_user(u)]

    def update_user_admin(
        self,
        user_id: str,
        *,
        role: str | None = None,
        status: str | None = None,
        nickname: str | None = None,
        password: str | None = None,
    ) -> dict[str, Any]:
        user = self.find_user_by_id(user_id)
        if not user:
            raise ValueError("用户不存在")
        values: dict[str, Any] = {}
        if role is not None:
            values["role"] = normalize_role(role)
        if status is not None:
            status = str(status).strip().lower()
            if status not in {"active", "disabled"}:
                raise ValueError("status 无效")
            values["status"] = status
        if nickname is not None:
            nickname = str(nickname).strip()
            if len(nickname) < 2 or len(nickname) > 32:
                raise ValueError("昵称长度应为 2-32 字")
            values["nickname"] = nickname
        if password is not None:
            try:
                require_strong_password(password, label="管理员设置的新密码")
            except RuntimeError as exc:
                raise ValueError(str(exc)) from exc
            values["password_hash"] = hash_password(password)
        if values:
            update = self._sa["update"]
            with self.engine.begin() as conn:
                conn.execute(update(self.users).where(self.users.c.id == user_id).values(**values))
        if (
            password is not None
            or values.get("role") not in {None, ROLES["ADMIN"]}
            or values.get("status") == "disabled"
        ):
            self.delete_sessions_for_user(user_id)
        updated = self.find_user_by_id(user_id)
        if not updated:
            raise ValueError("用户不存在")
        return updated

    def _row_to_notebook(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        mapping = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
        created = mapping.get("created_at")
        if isinstance(created, datetime):
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            created_at = created.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        else:
            created_at = created
        helpful_raw = mapping.get("helpful")
        return {
            "id": mapping.get("id"),
            "user_id": mapping.get("user_id"),
            "problem": mapping.get("problem"),
            "topic": mapping.get("topic") or "general",
            "helpful": str(helpful_raw).lower() in {"1", "true", "yes"},
            "note": mapping.get("note") or "",
            "stage": mapping.get("stage"),
            "final_answer": mapping.get("final_answer"),
            "reply": mapping.get("reply"),
            "created_at": created_at,
            "attempt_count": 0,
            "correct_count": 0,
            "latest_attempt": None,
        }

    def _row_to_notebook_attempt(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        mapping = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
        created = mapping.get("created_at")
        if isinstance(created, datetime):
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            created_at = created.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        else:
            created_at = created
        correct_raw = mapping.get("correct")
        return {
            "id": mapping.get("id"),
            "notebook_item_id": mapping.get("notebook_item_id"),
            "user_id": mapping.get("user_id"),
            "attempt_number": int(mapping.get("attempt_number") or 0),
            "answer": mapping.get("answer"),
            "correct": str(correct_raw).lower() in {"1", "true", "yes"},
            "hint_level": int(mapping.get("hint_level") or 0),
            "created_at": created_at,
        }

    def save_notebook_item(
        self,
        *,
        user_id: str,
        problem: str,
        topic: str,
        helpful: bool,
        note: str = "",
        stage: str | None = None,
        final_answer: str | None = None,
        reply: str | None = None,
    ) -> dict[str, Any]:
        problem = str(problem or "").strip()
        if not problem:
            raise ValueError("题面不能为空")
        select = self._sa["select"]
        insert = self._sa["insert"]
        update = self._sa["update"]
        values = {
            "topic": topic or "general",
            "helpful": "1" if helpful else "0",
            "note": (note or "")[:500],
            "stage": stage,
            "final_answer": (final_answer or None),
            "reply": (reply or None),
            "created_at": _utc_now(),
        }
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(self.notebook_items).where(
                    (self.notebook_items.c.user_id == user_id)
                    & (self.notebook_items.c.problem == problem)
                )
            ).first()
            if existing:
                item_id = existing._mapping["id"]
                conn.execute(
                    update(self.notebook_items)
                    .where(self.notebook_items.c.id == item_id)
                    .values(**values)
                )
            else:
                item_id = _generate_id("note")
                conn.execute(
                    insert(self.notebook_items).values(
                        id=item_id,
                        user_id=user_id,
                        problem=problem,
                        **values,
                    )
                )
            row = conn.execute(
                select(self.notebook_items).where(self.notebook_items.c.id == item_id)
            ).first()
        item = self._row_to_notebook(row)
        if not item:
            raise ValueError("保存错题本失败")
        return item

    def list_notebook_items(
        self,
        user_id: str,
        *,
        filter_kind: str = "all",
        topic: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        select = self._sa["select"]
        stmt = select(self.notebook_items).where(self.notebook_items.c.user_id == user_id)
        if filter_kind == "wrong":
            stmt = stmt.where(self.notebook_items.c.helpful == "0")
        elif filter_kind == "mastered":
            stmt = stmt.where(self.notebook_items.c.helpful == "1")
        if topic:
            stmt = stmt.where(self.notebook_items.c.topic == topic)
        limit = max(1, min(100, int(limit or 50)))
        stmt = stmt.order_by(self.notebook_items.c.created_at.desc()).limit(limit)
        with self.engine.begin() as conn:
            rows = conn.execute(stmt).fetchall()
        items = [item for item in (self._row_to_notebook(row) for row in rows) if item]
        return self._attach_notebook_attempt_summary(user_id, items)

    def _attach_notebook_attempt_summary(
        self, user_id: str, items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if not items:
            return items
        select = self._sa["select"]
        func = self._sa["func"]
        by_item: dict[str, dict[str, Any]] = {}
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(
                    self.notebook_attempts.c.notebook_item_id,
                    func.count(),
                    func.sum(self.notebook_attempts.c.correct == "1"),
                    func.max(self.notebook_attempts.c.created_at),
                )
                .where(self.notebook_attempts.c.user_id == user_id)
                .group_by(self.notebook_attempts.c.notebook_item_id)
            ).fetchall()
            latest_rows = conn.execute(
                select(self.notebook_attempts)
                .where(self.notebook_attempts.c.user_id == user_id)
                .order_by(
                    self.notebook_attempts.c.notebook_item_id,
                    self.notebook_attempts.c.attempt_number.desc(),
                )
            ).fetchall()
        latest_by_item: dict[str, dict[str, Any]] = {}
        consecutive_wrong_by_item: dict[str, int] = {}
        for row in latest_rows:
            latest = self._row_to_notebook_attempt(row)
            if latest:
                item_id = str(latest.get("notebook_item_id"))
                if item_id not in latest_by_item:
                    latest_by_item[item_id] = latest
                    if latest.get("correct"):
                        consecutive_wrong_by_item[item_id] = 0
                    else:
                        consecutive_wrong_by_item[item_id] = 1
                elif not latest.get("correct") and consecutive_wrong_by_item.get(item_id, 0) > 0:
                    consecutive_wrong_by_item[item_id] += 1
        for row in rows:
            by_item[str(row[0])] = {
                "count": int(row[1] or 0),
                "correct": int(row[2] or 0),
                "latest": row[3],
            }
        for item in items:
            summary = by_item.get(str(item["id"]))
            if not summary:
                continue
            latest = summary["latest"]
            if isinstance(latest, datetime):
                if latest.tzinfo is None:
                    latest = latest.replace(tzinfo=timezone.utc)
                latest = latest.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            item["attempt_count"] = summary["count"]
            item["correct_count"] = summary["correct"]
            item["latest_attempt_at"] = latest
            item["latest_attempt"] = latest
            latest_attempt = latest_by_item.get(str(item["id"]))
            item["latest_correct"] = bool(latest_attempt and latest_attempt.get("correct"))
            item["consecutive_wrong"] = consecutive_wrong_by_item.get(str(item["id"]), 0)
        return items

    def list_notebook_item_overviews(self, user_id: str) -> list[dict[str, Any]]:
        select = self._sa["select"]
        stmt = select(
            self.notebook_items.c.problem,
            self.notebook_items.c.topic,
            self.notebook_items.c.helpful,
        ).where(self.notebook_items.c.user_id == user_id)
        with self.engine.begin() as conn:
            rows = conn.execute(stmt).fetchall()
        return [
            {
                "problem": row[0],
                "topic": row[1],
                "helpful": str(row[2]).lower() in {"1", "true", "yes"},
            }
            for row in rows
        ]

    def get_notebook_item(self, user_id: str, item_id: str) -> dict[str, Any] | None:
        select = self._sa["select"]
        with self.engine.begin() as conn:
            row = conn.execute(
                select(self.notebook_items).where(
                    (self.notebook_items.c.id == item_id)
                    & (self.notebook_items.c.user_id == user_id)
                )
            ).first()
        item = self._row_to_notebook(row)
        return self._attach_notebook_attempt_summary(user_id, [item])[0] if item else None

    def list_notebook_attempts(
        self, user_id: str, item_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        select = self._sa["select"]
        limit = max(1, min(100, int(limit or 50)))
        stmt = (
            select(self.notebook_attempts)
            .where(
                (self.notebook_attempts.c.notebook_item_id == item_id)
                & (self.notebook_attempts.c.user_id == user_id)
            )
            .order_by(self.notebook_attempts.c.attempt_number.desc())
            .offset(max(0, int(offset or 0)))
            .limit(limit)
        )
        with self.engine.begin() as conn:
            rows = conn.execute(stmt).fetchall()
        return [item for item in (self._row_to_notebook_attempt(row) for row in rows) if item]

    def count_notebook_attempts(self, user_id: str, item_id: str) -> int:
        select = self._sa["select"]
        func = self._sa["func"]
        with self.engine.begin() as conn:
            return int(
                conn.execute(
                    select(func.count()).select_from(self.notebook_attempts).where(
                        (self.notebook_attempts.c.notebook_item_id == item_id)
                        & (self.notebook_attempts.c.user_id == user_id)
                    )
                ).scalar()
                or 0
            )

    def record_notebook_attempt(
        self,
        *,
        user_id: str,
        item_id: str,
        answer: str,
        evaluate_answer: Callable[[dict[str, Any]], bool],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        answer = str(answer or "").strip()
        if not answer:
            raise ValueError("答案不能为空")
        select = self._sa["select"]
        insert = self._sa["insert"]
        update = self._sa["update"]
        func = self._sa["func"]
        with _LOCK:
            with self.engine.begin() as conn:
                conn.execute(
                    update(self.notebook_items)
                    .where(
                        (self.notebook_items.c.id == item_id)
                        & (self.notebook_items.c.user_id == user_id)
                    )
                    .values(helpful=self.notebook_items.c.helpful)
                )
                item_row = conn.execute(
                    select(self.notebook_items).where(
                        (self.notebook_items.c.id == item_id)
                        & (self.notebook_items.c.user_id == user_id)
                    )
                ).first()
                if not item_row:
                    raise ValueError("错题不存在")
                item = dict(item_row._mapping)
                if str(item.get("helpful")).lower() in {"1", "true", "yes"}:
                    raise NotebookConflictError("这题已掌握，无需重复重练")
                correct = evaluate_answer(item)
                attempt_number = int(
                    conn.execute(
                        select(func.count()).select_from(self.notebook_attempts).where(
                            (self.notebook_attempts.c.notebook_item_id == item_id)
                            & (self.notebook_attempts.c.user_id == user_id)
                        )
                    ).scalar()
                    or 0
                ) + 1
                attempt_id = _generate_id("attempt")
                conn.execute(
                    insert(self.notebook_attempts).values(
                        id=attempt_id,
                        notebook_item_id=item_id,
                        user_id=user_id,
                        attempt_number=attempt_number,
                        answer=answer[:500],
                        correct="1" if correct else "0",
                        hint_level=0 if correct else min(3, attempt_number),
                        created_at=_utc_now(),
                    )
                )
                if correct:
                    conn.execute(
                        update(self.notebook_items)
                        .where(self.notebook_items.c.id == item_id)
                        .values(helpful="1")
                    )
                attempt_row = conn.execute(
                    select(self.notebook_attempts).where(self.notebook_attempts.c.id == attempt_id)
                ).first()
        attempt = self._row_to_notebook_attempt(attempt_row)
        if not attempt:
            raise ValueError("保存重练记录失败")
        item = self.get_notebook_item(user_id, item_id)
        if not item:
            raise ValueError("错题不存在")
        return attempt, item

    def mark_notebook_mastered(
        self,
        user_id: str,
        item_id: str,
        answer_available: Callable[[dict[str, Any]], bool],
    ) -> dict[str, Any]:
        update = self._sa["update"]
        select = self._sa["select"]
        func = self._sa["func"]
        with _LOCK:
            with self.engine.begin() as conn:
                conn.execute(
                    update(self.notebook_items)
                    .where(
                        (self.notebook_items.c.id == item_id)
                        & (self.notebook_items.c.user_id == user_id)
                    )
                    .values(helpful=self.notebook_items.c.helpful)
                )
                item_row = conn.execute(
                    select(self.notebook_items).where(
                        (self.notebook_items.c.id == item_id)
                        & (self.notebook_items.c.user_id == user_id)
                    )
                ).first()
                if not item_row:
                    raise ValueError("错题不存在")
                item = dict(item_row._mapping)
                if str(item.get("helpful")).lower() in {"1", "true", "yes"}:
                    raise NotebookConflictError("这题已掌握，无需重复标记")
                summary = conn.execute(
                    select(
                        func.count(),
                        func.sum(self.notebook_attempts.c.correct == "1"),
                        func.max(self.notebook_attempts.c.hint_level),
                    )
                    .where(
                        (self.notebook_attempts.c.notebook_item_id == item_id)
                        & (self.notebook_attempts.c.user_id == user_id)
                    )
                ).first()
                attempt_count = int(summary[0] or 0)
                correct_count = int(summary[1] or 0)
                highest_hint_level = int(summary[2] or 0)
                if (
                    attempt_count < 3
                    or correct_count != 0
                    or highest_hint_level < 3
                    or not answer_available(item)
                ):
                    raise NotebookConflictError("需第三次答错并查看参考答案后才能标记掌握")
                conn.execute(
                    update(self.notebook_items)
                    .where(self.notebook_items.c.id == item_id)
                    .values(helpful="1")
                )
        item = self.get_notebook_item(user_id, item_id)
        if not item:
            raise ValueError("错题不存在")
        return item

    def notebook_stats(self, user_id: str) -> dict[str, int]:
        select = self._sa["select"]
        func = self._sa["func"]
        with self.engine.begin() as conn:
            total = conn.execute(
                select(func.count()).select_from(self.notebook_items).where(
                    self.notebook_items.c.user_id == user_id
                )
            ).scalar() or 0
            mastered = conn.execute(
                select(func.count()).select_from(self.notebook_items).where(
                    (self.notebook_items.c.user_id == user_id)
                    & (self.notebook_items.c.helpful == "1")
                )
            ).scalar() or 0
        total = int(total)
        mastered = int(mastered)
        return {"total": total, "mastered": mastered, "wrong": max(0, total - mastered)}

    def delete_notebook_item(self, user_id: str, item_id: str) -> bool:
        delete = self._sa["delete"]
        with self.engine.begin() as conn:
            conn.execute(
                delete(self.notebook_attempts).where(
                    (self.notebook_attempts.c.notebook_item_id == item_id)
                    & (self.notebook_attempts.c.user_id == user_id)
                )
            )
            result = conn.execute(
                delete(self.notebook_items).where(
                    (self.notebook_items.c.id == item_id)
                    & (self.notebook_items.c.user_id == user_id)
                )
            )
        return bool(getattr(result, "rowcount", 0))

    def stats(self) -> dict[str, Any]:
        select = self._sa["select"]
        func = self._sa["func"]
        with self.engine.begin() as conn:
            users = [self._row_to_user(row) for row in conn.execute(select(self.users)).fetchall()]
            sessions_total = conn.execute(select(func.count()).select_from(self.sessions)).scalar() or 0
        by_role: dict[str, int] = {"student": 0, "teacher": 0, "admin": 0}
        active = 0
        for user in users:
            if not user:
                continue
            role = normalize_role(user.get("role"))
            by_role[role] = by_role.get(role, 0) + 1
            if (user.get("status") or "active") == "active":
                active += 1
        return {
            "users_total": len([u for u in users if u]),
            "users_active": active,
            "users_by_role": by_role,
            "sessions_total": int(sessions_total),
            "db_backend": self.backend,
        }

    def backend_info(self) -> dict[str, str]:
        return {
            "backend": self.backend,
            "database_url": self._safe_url(),
        }

    def _safe_url(self) -> str:
        url = self.database_url
        if "://" not in url:
            return url
        scheme, rest = url.split("://", 1)
        if "@" in rest and ":" in rest.split("@", 1)[0]:
            creds, hostpart = rest.split("@", 1)
            user = creds.split(":", 1)[0]
            return f"{scheme}://{user}:***@{hostpart}"
        return url


def create_auth_store() -> AuthStore:
    return AuthStore()


AUTH_STORE = create_auth_store()
