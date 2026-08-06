import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def auth_client(tmp_path, monkeypatch):
    db_file = tmp_path / "auth-db.json"
    monkeypatch.setenv("MATH_COACH_AUTH_DB", str(db_file))
    monkeypatch.setenv("MATH_COACH_AUTH_TEST_MODE", "1")
    monkeypatch.setenv("MATH_COACH_AUTH_REQUIRED", "true")
    monkeypatch.setenv("SEED_DEMO_ACCOUNTS", "true")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@test.local")
    monkeypatch.setenv("ADMIN_PASSWORD", "demo123")
    monkeypatch.setenv("DEMO_TEACHER_EMAIL", "teacher@test.local")
    monkeypatch.setenv("DEMO_TEACHER_PASSWORD", "demo123")
    monkeypatch.setenv("DEMO_STUDENT_EMAIL", "student@test.local")
    monkeypatch.setenv("DEMO_STUDENT_PASSWORD", "demo123")
    monkeypatch.delenv("VLLM_OMNI_URL", raising=False)
    monkeypatch.delenv("MINICPM_GATEWAY_URL", raising=False)

    # Reload modules so AuthStore picks up env.
    import importlib
    import teaching.auth_store as auth_store
    import teaching.deps as deps
    import app as app_module

    importlib.reload(auth_store)
    importlib.reload(deps)
    importlib.reload(app_module)
    return TestClient(app_module.app), auth_store.AUTH_STORE


def _login(client, email, password):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    payload = response.json()
    return payload["token"], payload["user"]


def test_seeded_admin_can_login(auth_client):
    client, _ = auth_client
    token, user = _login(client, "admin@test.local", "demo123")
    assert user["role"] == "admin"
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "admin@test.local"


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
    assert payload["token"]


def test_teaching_apis_require_login(auth_client):
    client, _ = auth_client
    unauthorized = client.post(
        "/api/lesson",
        json={"problem": "解方程：2x + 5 = 17。", "message": "给我一个提示", "stage": "hint"},
    )
    assert unauthorized.status_code == 401

    token, _ = _login(client, "student@test.local", "demo123")
    ok = client.post(
        "/api/lesson",
        json={"problem": "解方程：2x + 5 = 17。", "message": "给我一个提示", "stage": "hint"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert ok.status_code == 200
    assert ok.json()["final_answer"] is None


def test_admin_can_list_and_disable_user(auth_client):
    client, store = auth_client
    admin_token, _ = _login(client, "admin@test.local", "demo123")
    student_token, student = _login(client, "student@test.local", "demo123")

    listed = client.get("/api/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    assert listed.status_code == 200
    assert any(item["email"] == "student@test.local" for item in listed.json())

    forbidden = client.get("/api/admin/users", headers={"Authorization": f"Bearer {student_token}"})
    assert forbidden.status_code == 403

    patched = client.patch(
        f"/api/admin/users/{student['id']}",
        json={"status": "disabled"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert patched.status_code == 200
    assert patched.json()["user"]["status"] == "disabled"

    blocked = client.post(
        "/api/lesson",
        json={"problem": "1+1=?", "message": "提示", "stage": "hint"},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert blocked.status_code == 401


def test_health_reports_auth_required(auth_client):
    client, _ = auth_client
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["auth_required"] is True
