from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from teaching.auth_store import AuthStore
from teaching.runtime_env import load_runtime_env


def reset_student(email: str, password: str) -> dict[str, str]:
    store = AuthStore()
    user = store.find_user_by_email(email)
    if user:
        updated = store.update_user_admin(
            user["id"],
            role="student",
            status="active",
            nickname="比赛体验学生",
            password=password,
        )
        user_id = str(updated["id"])
    else:
        created = store.create_user(
            email=email,
            password=password,
            nickname="比赛体验学生",
            role="student",
            grade="grade8",
        )
        user_id = str(created["id"])

    store.delete_sessions_for_user(user_id)
    with store.engine.begin() as conn:
        conn.execute(store.notebook_attempts.delete().where(store.notebook_attempts.c.user_id == user_id))
        conn.execute(store.notebook_items.delete().where(store.notebook_items.c.user_id == user_id))
    return {"email": email, "user_id": user_id}


def write_secret(password: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    output.write_text(f"MATH_COACH_COMPETITION_PASSWORD={password}\n", encoding="utf-8")
    output.chmod(0o600)
    if output.stat().st_mode & 0o077:
        output.unlink(missing_ok=True)
        raise RuntimeError(
            f"Refusing to keep the demo password at {output}: "
            "the filesystem did not apply owner-only permissions. "
            "Use MATH_COACH_COMPETITION_PASSWORD or a secret path on a POSIX filesystem."
        )


def main() -> int:
    load_runtime_env()
    parser = argparse.ArgumentParser(description="Create or reset a clean competition demo student")
    parser.add_argument("--email", default=os.getenv("MATH_COACH_COMPETITION_EMAIL", "student@competition.local"))
    parser.add_argument("--password-env", default="MATH_COACH_COMPETITION_PASSWORD")
    parser.add_argument("--secret-file", type=Path, default=ROOT / ".competition.env")
    args = parser.parse_args()

    password = os.getenv(args.password_env, "").strip()
    generated = False
    if not password:
        password = secrets.token_urlsafe(18)
        generated = True
    info = reset_student(args.email.strip().lower(), password)
    if generated:
        write_secret(password, args.secret_file)
        print(f"Demo account reset. Password saved to {args.secret_file} (not printed).")
    else:
        print("Demo account reset using the provided environment password.")
    print(f"email={info['email']}")
    print("server_state=login_sessions_notebook_attempts_reset")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
