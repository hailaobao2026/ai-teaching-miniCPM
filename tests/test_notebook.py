import importlib

import pytest
from fastapi.testclient import TestClient

from teaching.answers import answers_equivalent
from teaching.practice import classify_topic, practice_bank, recommend_practice

STRONG_PASSWORD = "TestPassw0rd!"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MATH_COACH_AUTH_DB", str(tmp_path / "auth-db-notebook.json"))
    monkeypatch.setenv("MATH_COACH_SQLITE_PATH", str(tmp_path / "math-coach-notebook.db"))
    monkeypatch.setenv("MATH_COACH_AUTH_REQUIRED", "false")
    monkeypatch.setenv("SEED_DEMO_ACCOUNTS", "false")
    monkeypatch.setenv("MATH_COACH_RATE_LIMIT_PER_MINUTE", "0")
    monkeypatch.setenv("MATH_COACH_AUTH_RATE_LIMIT_PER_MINUTE", "0")
    monkeypatch.setenv("VLLM_OMNI_URL", "")
    monkeypatch.delenv("MINICPM_GATEWAY_URL", raising=False)

    import teaching.auth_store as auth_store
    import teaching.deps as deps
    import teaching.security as security
    import app as app_module

    importlib.reload(auth_store)
    importlib.reload(deps)
    importlib.reload(security)
    importlib.reload(app_module)
    test_client = TestClient(app_module.app)
    registered = test_client.post(
        "/api/auth/register",
        json={
            "email": "notebook-test@example.com",
            "password": STRONG_PASSWORD,
            "nickname": "错题测试",
            "role": "student",
            "grade": "grade8",
        },
    )
    assert registered.status_code == 200
    return test_client


@pytest.fixture()
def auth_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MATH_COACH_AUTH_DB", str(tmp_path / "auth-db-notebook-auth.json"))
    monkeypatch.setenv("MATH_COACH_SQLITE_PATH", str(tmp_path / "math-coach-notebook-auth.db"))
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

    import teaching.auth_store as auth_store
    import teaching.deps as deps
    import teaching.security as security
    import app as app_module

    importlib.reload(auth_store)
    importlib.reload(deps)
    importlib.reload(security)
    importlib.reload(app_module)
    return TestClient(app_module.app)


def _login(client, email, password):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    assert "token" not in response.json()


def test_classify_topic_covers_core_categories():
    assert classify_topic("解方程：2x + 5 = 17。") == "equation"
    assert classify_topic("分解因式：x² - 9") == "factor"
    assert classify_topic("直线 y = 2x - 3 与 x 轴交于点 A，求点 A 的坐标。") == "function"
    assert classify_topic("在三角形 ABC 中，底边 BC=8，高 AD=5，求三角形 ABC 的面积。") == "geometry"
    assert classify_topic("点 A(-2,3) 关于 x 轴的对称点是什么？") == "coordinate"


def test_recommend_excludes_current_problem_and_prefers_same_topic():
    payload = recommend_practice(problem="解方程：2x + 5 = 17。", limit=3)
    assert payload["topic"] == "equation"
    problems = [item["problem"] for item in payload["items"]]
    assert "解方程：2x + 5 = 17。" not in problems
    assert payload["items"]
    assert payload["items"][0]["topic"] == "equation"


def test_practice_bank_is_fixed_thirty_questions_and_same_topic_only():
    assert len(practice_bank()) == 30
    payload = recommend_practice(problem="解方程：2x + 5 = 17。", limit=8)
    assert len(payload["items"]) > 0
    assert all(item["topic"] == payload["topic"] for item in payload["items"])
    assert all("final_answer" not in item for item in payload["items"])


def test_feedback_persists_to_notebook(client):
    created = client.post(
        "/api/feedback",
        json={"problem": "解方程：2x + 5 = 17。", "helpful": False, "note": "第二步卡住了"},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "accepted"
    assert body["item"]["helpful"] is False
    assert body["item"]["topic"] == "equation"

    listed = client.get("/api/notebook?filter=wrong")
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["stats"]["wrong"] == 1
    assert payload["items"][0]["note"] == "第二步卡住了"

    deleted = client.delete(f"/api/notebook/{payload['items'][0]['id']}")
    assert deleted.json() == {"deleted": True}
    empty = client.get("/api/notebook")
    assert empty.json()["stats"]["total"] == 0


def test_feedback_upserts_same_problem(client):
    first = client.post(
        "/api/feedback",
        json={"problem": "矩形长 6，宽 4，求面积。", "helpful": False},
    ).json()["item"]
    second = client.post(
        "/api/feedback",
        json={"problem": "矩形长 6，宽 4，求面积。", "helpful": True, "note": "现在会了"},
    ).json()["item"]
    assert first["id"] == second["id"]
    listed = client.get("/api/notebook?filter=mastered")
    assert listed.json()["stats"]["mastered"] == 1
    assert listed.json()["items"][0]["note"] == "现在会了"


def test_practice_recommend_api(client):
    response = client.post(
        "/api/practice/recommend",
        json={"problem": "解方程：2x + 5 = 17。", "limit": 3},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["topic"] == "equation"
    assert 1 <= len(payload["items"]) <= 3
    assert all("problem" in item and "reason" in item for item in payload["items"])


def test_notebook_is_user_scoped(auth_client):
    client = auth_client
    _login(client, "student@test.local", STRONG_PASSWORD)
    saved = client.post("/api/feedback", json={"problem": "解方程：3x - 4 = 11。", "helpful": False})
    assert saved.status_code == 200

    client.post("/api/auth/logout")
    _login(client, "teacher@test.local", STRONG_PASSWORD)
    listed = client.get("/api/notebook")
    assert listed.status_code == 200
    assert listed.json()["items"] == []
    assert listed.json()["stats"]["total"] == 0


def test_answer_equivalence_supports_middle_school_forms():
    assert answers_equivalent("x = 6", "6")
    assert answers_equivalent("(3/2, 0)", "(1.5，0)")
    assert answers_equivalent("7√2", "7sqrt(2)")
    assert answers_equivalent("(x - 3)(x + 3)", "(x-3)(x+3)")
    assert answers_equivalent("x^2 - 9", "(x-3)(x+3)")
    assert answers_equivalent("28.26", "28.26平方单位")
    assert not answers_equivalent("x = 6", "x = 5")
    assert not answers_equivalent("x = 6", "y = 6")
    assert not answers_equivalent("√17", "√16")


def test_retry_attempt_flow_persists_history_and_reveals_progressively(client):
    saved = client.post(
        "/api/feedback",
        json={
            "problem": "解方程：2x + 5 = 17。",
            "helpful": False,
            "final_answer": "x = 6",
        },
    )
    assert saved.status_code == 200
    item = saved.json()["item"]
    assert item["final_answer"] is None
    assert item["attempt_count"] == 0

    first = client.post(f"/api/notebook/{item['id']}/attempts", json={"answer": "5"})
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["correct"] is False
    assert first_body["hint"]["level"] == 1
    assert first_body["final_answer"] is None
    assert first_body["can_mark_mastered"] is False
    denied = client.post(f"/api/notebook/{item['id']}/mastered")
    assert denied.status_code == 400

    second = client.post(f"/api/notebook/{item['id']}/attempts", json={"answer": "7"})
    assert second.json()["hint"]["level"] == 2
    assert second.json()["final_answer"] is None

    third = client.post(f"/api/notebook/{item['id']}/attempts", json={"answer": "8"})
    third_body = third.json()
    assert third_body["hint"]["level"] == 3
    assert third_body["final_answer"] == "x = 6"
    assert third_body["can_mark_mastered"] is True
    assert third_body["item"]["attempt_count"] == 3
    assert third_body["item"]["correct_count"] == 0

    history = client.get(f"/api/notebook/{item['id']}/attempts")
    assert history.status_code == 200
    history_body = history.json()
    assert len(history_body["attempts"]) == 3
    assert history_body["pagination"] == {"total": 3, "limit": 50, "offset": 0}
    assert history_body["item"]["consecutive_wrong"] == 3
    assert history_body["item"]["latest_correct"] is False

    mastered = client.post(f"/api/notebook/{item['id']}/mastered")
    assert mastered.status_code == 200
    assert mastered.json()["item"]["helpful"] is True

    denied_after_mastered = client.post(f"/api/notebook/{item['id']}/attempts", json={"answer": "6"})
    assert denied_after_mastered.status_code == 400


def test_correct_retry_marks_mastered_once(client):
    saved = client.post(
        "/api/feedback",
        json={
            "problem": "直线 y = 2x - 3 与 x 轴交于点 A，求点 A 的坐标。",
            "helpful": False,
            "final_answer": "(3/2, 0)",
        },
    )
    item = saved.json()["item"]
    response = client.post(f"/api/notebook/{item['id']}/attempts", json={"answer": "(1.5, 0)"})
    assert response.status_code == 200
    body = response.json()
    assert body["correct"] is True
    assert body["hint"]["level"] == 0
    assert body["item"]["helpful"] is True
    assert body["item"]["attempt_count"] == 1
    assert body["item"]["correct_count"] == 1


def test_retry_can_use_builtin_answer_and_reject_mastered_retry(client):
    saved = client.post(
        "/api/feedback",
        json={"problem": "圆的半径为 3，取 π=3.14，求面积。", "helpful": False},
    )
    item = saved.json()["item"]
    assert item["final_answer"] is None

    correct = client.post(f"/api/notebook/{item['id']}/attempts", json={"answer": "28.26"})
    assert correct.status_code == 200
    assert correct.json()["correct"] is True

    repeated = client.post(f"/api/notebook/{item['id']}/attempts", json={"answer": "28.26"})
    assert repeated.status_code == 400


def test_bank_answer_is_revealed_on_third_wrong_attempt(client):
    saved = client.post(
        "/api/feedback",
        json={"problem": "圆的半径为 3，取 π=3.14，求面积。", "helpful": False},
    )
    item = saved.json()["item"]
    for answer in ("1", "2", "3"):
        response = client.post(f"/api/notebook/{item['id']}/attempts", json={"answer": answer})
        assert response.status_code == 200

    third = response.json()
    assert third["final_answer"] == "28.26"
    assert third["can_mark_mastered"] is True
    mastered = client.post(f"/api/notebook/{item['id']}/mastered")
    assert mastered.status_code == 200


def test_manual_mastery_requires_an_answer_to_reveal(client):
    saved = client.post(
        "/api/feedback",
        json={"problem": "自定义没有答案的错题。", "helpful": False},
    )
    item = saved.json()["item"]
    for answer in ("1", "2", "3"):
        response = client.post(f"/api/notebook/{item['id']}/attempts", json={"answer": answer})
        assert response.status_code == 200

    assert response.json()["can_mark_mastered"] is False
    mastered = client.post(f"/api/notebook/{item['id']}/mastered")
    assert mastered.status_code == 400
