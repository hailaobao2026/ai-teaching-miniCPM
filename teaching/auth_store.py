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

import os
import secrets
import threading
import time
import uuid
from datetime import datetime, timezone
from hashlib import scrypt
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from teaching.rbac import ROLES, normalize_role, public_user

SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
_LOCK = threading.RLock()

# scrypt params: n=2**12 is demo-friendly; increase for higher-security deployments.
_SCRYPT_N = int(os.getenv("MATH_COACH_SCRYPT_N", str(2**12)))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _utc_now_iso() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")


def _generate_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


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
        password = os.getenv("MATH_COACH_MYSQL_PASSWORD", "mathcoach")
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
            seed = str(os.getenv("SEED_DEMO_ACCOUNTS", "true")).lower() != "false"
            admin_email = (os.getenv("ADMIN_EMAIL") or "teacher@demo.local").strip().lower()
            admin_password = os.getenv("ADMIN_PASSWORD") or "demo123"
            admin_nickname = os.getenv("ADMIN_NICKNAME") or "系统管理员"
            admin = self.find_user_by_email(admin_email)
            if not admin:
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

            teacher_email = (os.getenv("DEMO_TEACHER_EMAIL") or "math.teacher@demo.local").strip().lower()
            if not self.find_user_by_email(teacher_email):
                self._insert_user(
                    {
                        "id": _generate_id("user"),
                        "email": teacher_email,
                        "password_hash": hash_password(os.getenv("DEMO_TEACHER_PASSWORD") or "demo123"),
                        "nickname": os.getenv("DEMO_TEACHER_NICKNAME") or "数学老师",
                        "role": ROLES["TEACHER"],
                        "status": "active",
                        "grade_code": None,
                        "created_at": _utc_now(),
                    }
                )

            student_email = (os.getenv("DEMO_STUDENT_EMAIL") or "student@demo.local").strip().lower()
            if not self.find_user_by_email(student_email):
                self._insert_user(
                    {
                        "id": _generate_id("user"),
                        "email": student_email,
                        "password_hash": hash_password(os.getenv("DEMO_STUDENT_PASSWORD") or "demo123"),
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
                    token=token,
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
            row = conn.execute(select(self.sessions).where(self.sessions.c.token == token)).first()
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
                conn.execute(delete(self.sessions).where(self.sessions.c.token == token))
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
            conn.execute(delete(self.sessions).where(self.sessions.c.token == token))

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
            if len(password) < 8 or len(password) > 128:
                raise ValueError("密码长度应为 8-128 位")
            values["password_hash"] = hash_password(password)
        if values:
            update = self._sa["update"]
            with self.engine.begin() as conn:
                conn.execute(update(self.users).where(self.users.c.id == user_id).values(**values))
        updated = self.find_user_by_id(user_id)
        if not updated:
            raise ValueError("用户不存在")
        return updated

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
