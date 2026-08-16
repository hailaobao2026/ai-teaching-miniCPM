import importlib

import pytest
from fastapi.testclient import TestClient

STRONG_PASSWORD = "TestPassw0rd!"


@pytest.fixture()
def auth_client(tmp_path, monkeypatch):
    db_file = tmp_path / "auth-db.json"
    monkeypatch.setenv("MATH_COACH_AUTH_DB", str(db_file))
    monkeypatch.setenv("MATH_COACH_SQLITE_PATH", str(tmp_path / "math-coach.db"))
    monkeypatch.setenv("MATH_COACH_AUTH_TEST_MODE", "1")
    monkeypatch.setenv("MATH_COACH_AUTH_REQUIRED", "true")
    monkeypatch.setenv("SEED_DEMO_ACCOUNTS", "true")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@test.local")
    monkeypatch.setenv("ADMIN_PASSWORD", STRONG_PASSWORD)
    monkeypatch.setenv("DEMO_TEACHER_EMAIL", "teacher@test.local")
    monkeypatch.setenv("DEMO_TEACHER_PASSWORD", STRONG_PASSWORD)
    monkeypatch.setenv("DEMO_STUDENT_EMAIL", "student@test.local")
    monkeypatch.setenv("DEMO_STUDENT_PASSWORD", STRONG_PASSWORD)
    monkeypatch.setenv("MATH_COACH_COOKIE_SECURE", "false")
    monkeypatch.setenv("MATH_COACH_RATE_LIMIT_PER_MINUTE", "0")
    monkeypatch.setenv("MATH_COACH_AUTH_RATE_LIMIT_PER_MINUTE", "0")
    monkeypatch.setenv("VLLM_OMNI_URL", "")
    monkeypatch.delenv("MINICPM_GATEWAY_URL", raising=False)

    # Reload modules so AuthStore picks up env.
    import teaching.auth_store as auth_store
    import teaching.deps as deps
    import teaching.security as security
    import app as app_module

    importlib.reload(auth_store)
    importlib.reload(deps)
    importlib.reload(security)
    importlib.reload(app_module)
    # TestClient with cookies enabled (default) for HttpOnly session checks.
    return TestClient(app_module.app), auth_store.AUTH_STORE


def _login(client, email, password):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "math_coach_token" in response.cookies
    assert "token" not in payload
    return response.cookies.get("math_coach_token"), payload["user"]


def test_seeded_admin_can_login(auth_client):
    client, _ = auth_client
    token, user = _login(client, "admin@test.local", STRONG_PASSWORD)
    assert user["role"] == "admin"
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "admin@test.local"


def test_session_token_is_not_stored_in_plaintext(auth_client):
    client, store = auth_client
    token, _ = _login(client, "student@test.local", STRONG_PASSWORD)
    with store.engine.connect() as connection:
        stored = connection.exec_driver_sql("SELECT token FROM sessions").scalar()
    assert stored != token
    assert len(stored) == 64


def test_admin_cannot_reset_user_to_weak_password(auth_client):
    client, _ = auth_client
    admin_client = TestClient(client.app)
    _login(admin_client, "admin@test.local", STRONG_PASSWORD)
    student = store_student_for_test(client)
    response = admin_client.patch(
        f"/api/admin/users/{student['id']}",
        json={"password": "aaaaaaaa"},
    )
    assert response.status_code == 400


def store_student_for_test(client):
    created = client.post(
        "/api/auth/register",
        json={
            "email": "weak-target@test.local",
            "password": "Passw0rd1",
            "nickname": "目标学生",
            "role": "student",
        },
    )
    assert created.status_code == 200
    return created.json()["user"]


def test_login_sets_httponly_cookie_and_me_works_without_bearer(auth_client):
    client, _ = auth_client
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@test.local", "password": STRONG_PASSWORD},
    )
    assert response.status_code == 200
    assert response.json().get("cookie_auth") is True
    cookie = response.cookies.get("math_coach_token")
    assert cookie
    # Cookie-only path (no Authorization header).
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "admin@test.local"

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200
    blocked = client.get("/api/auth/me")
    assert blocked.status_code == 401


def test_register_student_and_reject_admin_role(auth_client):
    client, _ = auth_client
    denied = client.post(
        "/api/auth/register",
        json={
            "email": "new.admin@test.local",
            "password": "Passw0rd1",
            "nickname": "伪管理员",
            "role": "admin",
        },
    )
    assert denied.status_code == 400

    created = client.post(
        "/api/auth/register",
        json={
            "email": "new.student@test.local",
            "password": "Passw0rd1",
            "nickname": "新同学",
            "role": "student",
            "grade": "grade8",
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["user"]["role"] == "student"
    assert "token" not in payload
    assert "math_coach_token" in created.cookies


def test_teaching_apis_require_login(auth_client):
    client, _ = auth_client
    unauthorized = client.post(
        "/api/lesson",
        json={"problem": "解方程：2x + 5 = 17。", "message": "给我一个提示", "stage": "hint"},
    )
    assert unauthorized.status_code == 401

    token, _ = _login(client, "student@test.local", STRONG_PASSWORD)
    ok = client.post("/api/lesson", json={"problem": "解方程：2x + 5 = 17。", "message": "给我一个提示", "stage": "hint"})
    assert ok.status_code == 200
    assert ok.json()["final_answer"] is None


def test_admin_can_list_and_disable_user(auth_client):
    client, store = auth_client
    admin_client = TestClient(client.app)
    student_client = TestClient(client.app)
    _login(admin_client, "admin@test.local", STRONG_PASSWORD)
    _, student = _login(student_client, "student@test.local", STRONG_PASSWORD)

    listed = admin_client.get("/api/admin/users")
    assert listed.status_code == 200
    assert any(item["email"] == "student@test.local" for item in listed.json())

    forbidden = student_client.get("/api/admin/users")
    assert forbidden.status_code == 403

    patched = admin_client.patch(
        f"/api/admin/users/{student['id']}",
        json={"status": "disabled"},
    )
    assert patched.status_code == 200
    assert patched.json()["user"]["status"] == "disabled"

    blocked = student_client.post(
        "/api/lesson",
        json={"problem": "1+1=?", "message": "提示", "stage": "hint"},
    )
    assert blocked.status_code == 401


def test_health_reports_auth_required(auth_client):
    client, _ = auth_client
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["auth_required"] is True


def test_security_headers_present(auth_client):
    client, _ = auth_client
    response = client.get("/api/health")
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert "Content-Security-Policy" in response.headers
    assert "frame-src 'self' blob:" in response.headers["Content-Security-Policy"]
    permissions_policy = response.headers.get("Permissions-Policy", "")
    assert "camera=(self)" in permissions_policy
    assert "microphone=(self)" in permissions_policy


def test_reject_weak_seed_password(tmp_path, monkeypatch):
    monkeypatch.setenv("MATH_COACH_AUTH_DB", str(tmp_path / "auth-db.json"))
    monkeypatch.setenv("MATH_COACH_SQLITE_PATH", str(tmp_path / "math-coach.db"))
    monkeypatch.setenv("MATH_COACH_AUTH_TEST_MODE", "1")
    monkeypatch.setenv("SEED_DEMO_ACCOUNTS", "true")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@test.local")
    monkeypatch.setenv("ADMIN_PASSWORD", "demo123")
    monkeypatch.setenv("DEMO_TEACHER_PASSWORD", STRONG_PASSWORD)
    monkeypatch.setenv("DEMO_STUDENT_PASSWORD", STRONG_PASSWORD)
    monkeypatch.delenv("VLLM_OMNI_URL", raising=False)

    import teaching.auth_store as auth_store

    with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
        importlib.reload(auth_store)
        auth_store.AuthStore()
