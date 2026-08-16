import subprocess
import sys
from pathlib import Path


STRONG_PASSWORD = "TestPassw0rd!"


def test_auth_store_loads_admin_seed_from_env_file(tmp_path):
    database = tmp_path / "math-coach.db"
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "MATH_COACH_DB_BACKEND=sqlite",
                f"MATH_COACH_SQLITE_PATH={database}",
                "ADMIN_EMAIL=admin@test.local",
                f"ADMIN_PASSWORD={STRONG_PASSWORD}",
                "SEED_DEMO_ACCOUNTS=false",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from teaching.auth_store import AUTH_STORE, verify_password; "
            "user = AUTH_STORE.find_user_by_email('admin@test.local'); "
            "assert user is not None; "
            "assert verify_password('TestPassw0rd!', user['password_hash'])",
        ],
        env={
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
            "MATH_COACH_ENV_FILE": str(env_file),
        },
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
