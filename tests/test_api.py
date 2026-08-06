import base64
import io
import importlib
import wave

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MATH_COACH_AUTH_DB", str(tmp_path / "auth-db-api.json"))
    monkeypatch.setenv("MATH_COACH_AUTH_REQUIRED", "false")
    monkeypatch.setenv("SEED_DEMO_ACCOUNTS", "true")
    monkeypatch.delenv("VLLM_OMNI_URL", raising=False)
    monkeypatch.delenv("MINICPM_GATEWAY_URL", raising=False)

    import teaching.auth_store as auth_store
    import teaching.deps as deps
    import app as app_module

    importlib.reload(auth_store)
    importlib.reload(deps)
    importlib.reload(app_module)
    return TestClient(app_module.app)


def test_health_defaults_to_mock_mode(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["mode"] == "mock"


def test_recognize_returns_editable_problem(client):
    response = client.post("/api/recognize", data={"problem_text": "3x - 2 = 10"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["problem"] == "3x - 2 = 10"
    assert payload["needs_confirmation"] is True


def test_hint_does_not_reveal_answer_by_default(client):
    response = client.post(
        "/api/lesson",
        json={"problem": "解方程：2x + 5 = 17。", "message": "给我一个提示", "stage": "hint"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "mock"
    assert payload["final_answer"] is None
    assert "两边" in payload["reply"]
    assert "x = 6" not in payload["reply"]


def test_full_explanation_has_answer(client):
    response = client.post(
        "/api/lesson",
        json={"problem": "解方程：2x + 5 = 17。", "message": "请给完整解析", "stage": "explain"},
    )
    assert response.status_code == 200
    assert response.json()["final_answer"] == "x = 6"


def test_lesson_session_is_owned_by_backend(client):
    first = client.post(
        "/api/lesson",
        json={"problem": "解方程：2x + 5 = 17。", "message": "给我一个提示", "stage": "hint"},
    ).json()
    second = client.post(
        "/api/lesson",
        json={"session_id": first["session_id"], "problem": "解方程：2x + 5 = 17。", "message": "继续", "stage": "hint"},
    ).json()
    assert first["session_id"] == second["session_id"]
    deleted = client.delete(f"/api/session/{first['session_id']}")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}


def test_minicpm_adapter_uses_vllm_omni_openai_endpoint_and_image_data_url():
    from teaching.minicpm_client import MiniCPMClient

    adapter = MiniCPMClient("http://gpu.example.test:8099")
    assert adapter.completions_url == "http://gpu.example.test:8099/v1/chat/completions"
    payload = adapter._payload("识别题目", "请给提示", [], False, b"png-bytes", "image/png")
    content = payload["messages"][-1]["content"]
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"] == "data:image/png;base64,cG5nLWJ5dGVz"
    assert adapter.image_content(b"png-bytes", "image/png") == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,cG5nLWJ5dGVz"},
    }


def test_minicpm_payload_enables_vllm_tts_template():
    from teaching.minicpm_client import MiniCPMClient

    adapter = MiniCPMClient("http://gpu.example.test:8099")
    payload = adapter._payload("题目", "朗读解释", [], True)
    assert payload["modalities"] == ["text", "audio"]
    assert payload["chat_template_kwargs"] == {"use_tts_template": True}


def test_minicpm_sse_choice_events_support_text_and_audio():
    from teaching.minicpm_client import yield_from_events

    events = list(yield_from_events({"choices": [{"delta": {"content": "分步"}}, {"delta": {"audio": {"data": "YWJj"}}}]}))
    assert events == [
        {"type": "text_delta", "text_delta": "分步"},
        {"type": "audio_delta", "audio_data": "YWJj", "audio_mime": "audio/wav"},
    ]


def test_merge_audio_repairs_repeated_wav_headers():
    from teaching.minicpm_client import merge_audio

    def wav_chunk(pcm: bytes) -> bytes:
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(pcm)
        return output.getvalue()

    first = wav_chunk(b"\x00\x00\x01\x00")
    second = wav_chunk(b"\x02\x00\x03\x00")
    merged = merge_audio([base64.b64encode(first).decode(), base64.b64encode(second).decode()])
    assert merged is not None
    with wave.open(io.BytesIO(base64.b64decode(merged)), "rb") as wav:
        assert wav.getframerate() == 24000
        assert wav.getnframes() == 4
        assert wav.readframes(4) == b"\x00\x00\x01\x00\x02\x00\x03\x00"


def test_vllm_omni_url_takes_precedence_over_legacy_gateway_url(monkeypatch):
    from teaching.minicpm_client import configured_client

    monkeypatch.setenv("MINICPM_GATEWAY_URL", "http://legacy.example.test:8000")
    monkeypatch.setenv("VLLM_OMNI_URL", "http://omni.example.test:8099")
    configured = configured_client()
    assert configured is not None
    assert configured.completions_url == "http://omni.example.test:8099/v1/chat/completions"


def test_generated_markdown_can_be_shown_as_teaching_steps():
    from teaching.minicpm_client import structured_steps

    steps, answer = structured_steps("1. 先令 y=0\n2. 解得 x=3/2\n答案：x=3/2")
    assert len(steps) == 2
    assert answer == "x=3/2"


def test_stream_lesson_emits_deltas_and_final_contract(client):
    response = client.post(
        "/api/lesson/stream",
        json={"problem": "矩形长 6，宽 4，求面积。", "message": "给我一个提示", "stage": "hint", "tts": False},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert '"type": "text_delta"' in body
    assert '"type": "lesson"' in body
    assert '"type": "done"' in body


def test_recognition_parser_accepts_fenced_annotations():
    from teaching.recognition import parse_recognition

    problem, annotations = parse_recognition(
        '```json\n{"problem":"解方程：x+1=2","annotations":[{"label":"题目","x":0.1,"y":0.2,"width":0.7,"height":0.3}]}\n```'
    )
    assert problem == "解方程：x+1=2"
    assert annotations[0].label == "题目"


def test_recognition_parser_discards_out_of_bounds_boxes():
    from teaching.recognition import parse_recognition

    problem, annotations = parse_recognition(
        '模型输出：{"problem":"题面","annotations":[{"label":"越界","x":0.8,"y":0,"width":0.4,"height":0.2}]}'
    )
    assert problem == "题面"
    assert annotations == []
