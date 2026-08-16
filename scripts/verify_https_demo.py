from __future__ import annotations

import argparse
from pathlib import Path

import httpx


def load_password(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"Password file not found: {path}")
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("MATH_COACH_COMPETITION_PASSWORD="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(f"MATH_COACH_COMPETITION_PASSWORD missing in {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the public HTTPS competition demo")
    parser.add_argument("--url", required=True, help="For example https://math.example.com")
    parser.add_argument("--email", default="student@competition.local")
    parser.add_argument("--secret-file", type=Path, default=Path(".competition.env"))
    args = parser.parse_args()
    if not args.url.startswith("https://"):
        raise SystemExit("The demo URL must use HTTPS (camera/microphone require a secure context)")

    base = args.url.rstrip("/")
    password = load_password(args.secret_file)
    checks: list[tuple[str, bool, str]] = []
    with httpx.Client(timeout=httpx.Timeout(15, read=120), follow_redirects=False) as client:
        http_response = client.get(f"{base}/")
        checks.append(("https_home", http_response.status_code == 200, str(http_response.status_code)))
        checks.append((
            "hsts_header",
            "max-age=" in http_response.headers.get("strict-transport-security", "").lower(),
            http_response.headers.get("strict-transport-security", "missing"),
        ))

        health = client.get(f"{base}/api/health")
        health_payload = health.json()
        checks.append((
            "real_model_health",
            health.status_code == 200 and health_payload.get("mode") == "minicpm",
            f"mode={health_payload.get('mode')}, upstream={health_payload.get('upstream_configured')}",
        ))

        login = client.post(
            f"{base}/api/auth/login",
            json={"email": args.email, "password": password},
        )
        checks.append(("demo_login", login.status_code == 200, str(login.status_code)))
        if login.status_code != 200:
            print_checks(checks)
            return 1

        examples = client.get(f"{base}/api/examples")
        checks.append(("examples", examples.status_code == 200, str(examples.status_code)))

        stream = client.post(
            f"{base}/api/lesson/stream",
            json={
                "problem": "解方程：2x + 5 = 17。",
                "message": "请先确认题面，并给一个引导提示。",
                "stage": "confirm",
                "tts": False,
            },
        )
        body = stream.text
        checks.append((
            "lesson_stream",
            stream.status_code == 200
            and '"type": "text_delta"' in body
            and '"type": "lesson"' in body
            and '"type": "done"' in body,
            str(stream.status_code),
        ))
        checks.append((
            "real_model_lesson",
            stream.status_code == 200 and '"source": "minicpm"' in body,
            "source=minicpm" if '"source": "minicpm"' in body else "mock_or_degraded",
        ))

    print_checks(checks)
    return 0 if all(ok for _, ok, _ in checks) else 1


def print_checks(checks: list[tuple[str, bool, str]]) -> None:
    for name, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")


if __name__ == "__main__":
    raise SystemExit(main())
