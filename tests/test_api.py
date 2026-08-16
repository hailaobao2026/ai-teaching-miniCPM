import base64
import io
import importlib
import json
import wave

from PIL import Image
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MATH_COACH_AUTH_DB", str(tmp_path / "auth-db-api.json"))
    monkeypatch.setenv("MATH_COACH_SQLITE_PATH", str(tmp_path / "math-coach-api.db"))
    monkeypatch.setenv("MATH_COACH_AUTH_REQUIRED", "false")
    monkeypatch.setenv("SEED_DEMO_ACCOUNTS", "false")
    monkeypatch.setenv("MATH_COACH_RATE_LIMIT_PER_MINUTE", "0")
    monkeypatch.setenv("MATH_COACH_AUTH_RATE_LIMIT_PER_MINUTE", "0")
    monkeypatch.setenv("VLLM_OMNI_URL", "")
    monkeypatch.setenv("MINICPM_GATEWAY_URL", "")

    import teaching.auth_store as auth_store
    import teaching.deps as deps
    import teaching.security as security
    import app as app_module

    importlib.reload(auth_store)
    importlib.reload(deps)
    importlib.reload(security)
    importlib.reload(app_module)
    return TestClient(app_module.app)


def test_health_defaults_to_mock_mode(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["mode"] == "mock"


def test_anonymous_mode_bootstraps_frontend_user(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["user"]["id"] == "anonymous"


def test_recognize_returns_editable_problem(client):
    response = client.post("/api/recognize", data={"problem_text": "3x - 2 = 10"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["problem"] == "3x - 2 = 10"
    assert payload["needs_confirmation"] is True


def _pdf_bytes(page_count: int = 1) -> bytes:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument.new()
    for _ in range(page_count):
        document.new_page(300, 300)
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(output, format="PNG")
    return output.getvalue()


def test_recognize_accepts_valid_pdf(client):
    response = client.post(
        "/api/recognize",
        files={"file": ("problem.pdf", _pdf_bytes(), "application/pdf")},
        data={"problem_text": "3x - 2 = 10"},
    )
    assert response.status_code == 200
    assert response.json()["problem"] == "3x - 2 = 10"


def test_mock_recognized_image_keeps_short_lived_image_context(client):
    response = client.post(
        "/api/recognize",
        files={"file": ("problem.png", _png_bytes(), "image/png")},
        data={"problem_text": "3x - 2 = 10"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["problem"] == "3x - 2 = 10"
    assert payload["annotations"]
    assert payload["session_id"]

    import app as app_module

    session = app_module.ORCHESTRATOR.get_or_create(payload["session_id"], payload["problem"], "anonymous")
    assert session.id == payload["session_id"]
    assert session.image_mime == "image/jpeg"
    assert session.image_bytes.startswith(b"\xff\xd8\xff")


def test_mock_recognized_image_without_problem_returns_recoverable_empty_result(client):
    response = client.post(
        "/api/recognize",
        files={"file": ("not-a-problem.png", _png_bytes(), "image/png")},
        data={"problem_text": ""},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["no_problems"] is True
    assert payload["problems"] == []
    assert payload["problem"] == ""
    assert payload["session_id"] is None
    assert "重拍" in payload["message"]


def test_real_recognition_without_problem_returns_recoverable_empty_result(client, monkeypatch):
    monkeypatch.setenv("VLLM_OMNI_URL", "http://upstream.example.test:8099")
    import app as app_module

    importlib.reload(app_module)

    class EmptyClient:
        async def chat(self, *args, **kwargs):
            return {"text": "{\"problems\":[]}"}

    app_module.MINICPM_CLIENT = EmptyClient()
    response = client.post(
        "/api/recognize",
        files={"file": ("not-a-problem.png", _png_bytes(), "image/png")},
        data={"problem_text": ""},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["no_problems"] is True
    assert payload["source"] == "minicpm"
    assert payload["problems"] == []
    assert payload["session_id"] is None
    assert "手动输入" in payload["message"]

    monkeypatch.setenv("VLLM_OMNI_URL", "")
    importlib.reload(app_module)


def test_vision_image_is_resized_and_compressed_for_recognition(monkeypatch):
    from PIL import Image

    from app import _prepare_vision_image

    output = io.BytesIO()
    Image.new("RGB", (2400, 1200), "white").save(output, format="PNG")
    prepared, mime = _prepare_vision_image(output.getvalue(), "image/png")
    image = Image.open(io.BytesIO(prepared))
    assert mime == "image/jpeg"
    assert image.format == "JPEG"
    assert image.size == (1280, 640)
    assert len(prepared) < len(output.getvalue())


def test_recognize_rejects_oversized_pdf_page_count(client):
    response = client.post(
        "/api/recognize",
        files={"file": ("problem.pdf", _pdf_bytes(21), "application/pdf")},
        data={"problem_text": "3x - 2 = 10"},
    )
    assert response.status_code == 415
    assert response.json()["detail"] == "PDF 内容无效或超出页数限制"


def test_recognize_compresses_pdf_first_page_for_minicpm(client, monkeypatch):
    monkeypatch.setenv("VLLM_OMNI_URL", "http://upstream.example.test:8099")
    import app as app_module

    importlib.reload(app_module)

    class FakeClient:
        def __init__(self):
            self.calls = []

        async def chat(self, *args, **kwargs):
            normalized = dict(zip(("problem", "message", "history", "tts"), args))
            normalized.update(kwargs)
            kwargs = normalized
            self.calls.append(kwargs)
            return {
                "text": json.dumps(
                    {"problem": "PDF 中的题目", "annotations": []},
                    ensure_ascii=False,
                )
            }

    fake_client = FakeClient()
    app_module.MINICPM_CLIENT = fake_client
    response = client.post(
        "/api/recognize",
        files={"file": ("problem.pdf", _pdf_bytes(), "application/pdf")},
        data={"problem_text": ""},
    )
    assert response.status_code == 200
    assert response.json()["problem"] == "PDF 中的题目"
    assert response.json()["source"] == "minicpm"
    assert fake_client.calls[0]["image_mime"] == "image/jpeg"
    assert fake_client.calls[0]["image_bytes"].startswith(b"\xff\xd8\xff")

    monkeypatch.setenv("VLLM_OMNI_URL", "")
    importlib.reload(app_module)


def test_recognized_image_follows_edited_problem_into_lesson(client, monkeypatch):
    monkeypatch.setenv("VLLM_OMNI_URL", "http://upstream.example.test:8099")
    import app as app_module

    importlib.reload(app_module)

    class FakeClient:
        def __init__(self):
            self.calls = []

        async def chat(self, *args, **kwargs):
            normalized = dict(zip(("problem", "message", "history", "tts"), args))
            normalized.update(kwargs)
            kwargs = normalized
            self.calls.append(kwargs)
            if kwargs.get("stage") == "recognition":
                return {"text": json.dumps({"problem": "识别出的原题", "annotations": []}, ensure_ascii=False)}
            return {"text": "请先观察图形，再考虑边长关系。", "audio_base64": None, "audio_mime": None}

    fake_client = FakeClient()
    app_module.MINICPM_CLIENT = fake_client
    upstream_client = TestClient(app_module.app)
    recognized = upstream_client.post(
        "/api/recognize",
        files={"file": ("problem.png", _png_bytes(), "image/png")},
        data={"problem_text": ""},
    ).json()
    lesson = upstream_client.post(
        "/api/lesson",
        json={
            "session_id": recognized["session_id"],
            "problem": "学生修正后的几何题",
            "message": "给一个提示",
            "stage": "hint",
            "tts": False,
        },
    ).json()

    assert recognized["source"] == "minicpm"
    assert lesson["session_id"] == recognized["session_id"]
    assert fake_client.calls[1]["problem"] == "学生修正后的几何题"
    assert fake_client.calls[1]["image_bytes"] == fake_client.calls[0]["image_bytes"]
    assert fake_client.calls[1]["image_mime"] == "image/jpeg"

    monkeypatch.setenv("VLLM_OMNI_URL", "")
    importlib.reload(app_module)


def test_multi_page_pdf_recognizes_selectable_problems(client, monkeypatch):
    monkeypatch.setenv("VLLM_OMNI_URL", "http://upstream.example.test:8099")
    import app as app_module

    importlib.reload(app_module)

    class FakeClient:
        def __init__(self):
            self.calls = []

        async def chat(self, *args, **kwargs):
            normalized = dict(zip(("problem", "message", "history", "tts"), args))
            normalized.update(kwargs)
            kwargs = normalized
            self.calls.append(kwargs)
            page_problem = "第一题：2x + 5 = 17" if len(self.calls) == 1 else "第二题：3x - 4 = 11"
            return {
                "text": json.dumps(
                    {"problems": [{"problem": page_problem, "annotations": []}]},
                    ensure_ascii=False,
                )
            }

    fake_client = FakeClient()
    app_module.MINICPM_CLIENT = fake_client
    response = client.post(
        "/api/recognize",
        files={"file": ("problems.pdf", _pdf_bytes(2), "application/pdf")},
        data={"problem_text": ""},
    )
    payload = response.json()
    assert response.status_code == 200
    assert [item["problem"] for item in payload["problems"]] == ["第一题：2x + 5 = 17", "第二题：3x - 4 = 11"]
    assert [item["id"] for item in payload["problems"]] == ["problem-1", "problem-2"]
    assert payload["selected_problem_id"] == "problem-1"
    assert len(fake_client.calls) == 2
    assert all(isinstance(call["image_bytes"], bytes) for call in fake_client.calls[:2])
    assert all(call["image_bytes"].startswith(b"\xff\xd8\xff") for call in fake_client.calls[:2])

    lesson = client.post(
        "/api/lesson",
        json={
            "session_id": payload["session_id"],
            "problem": "第二题：3x - 4 = 11",
            "message": "给一个提示",
            "stage": "hint",
            "tts": False,
        },
    ).json()
    assert lesson["session_id"] == payload["session_id"]
    assert fake_client.calls[2]["problem"] == "第二题：3x - 4 = 11"
    assert fake_client.calls[2]["image_bytes"] == [call["image_bytes"] for call in fake_client.calls[:2]]

    monkeypatch.setenv("VLLM_OMNI_URL", "")
    importlib.reload(app_module)


def test_failed_recognition_degrades_visibly_and_keeps_image_for_retry(client, monkeypatch):
    monkeypatch.setenv("VLLM_OMNI_URL", "http://upstream.example.test:8099")
    import app as app_module

    importlib.reload(app_module)


def test_failed_real_recognition_without_text_does_not_fall_back_to_sample(client, monkeypatch):
    monkeypatch.setenv("VLLM_OMNI_URL", "http://upstream.example.test:8099")
    import app as app_module

    importlib.reload(app_module)

    class FailingClient:
        async def chat(self, *args, **kwargs):
            raise RuntimeError("vLLM-Omni HTTP 524: timeout")

    app_module.MINICPM_CLIENT = FailingClient()
    response = client.post(
        "/api/recognize",
        files={"file": ("problem.png", _png_bytes(), "image/png")},
        data={"problem_text": ""},
    )
    assert response.status_code == 502
    assert "MiniCPM-o 识题失败" in response.json()["detail"]
    assert "2x + 5 = 17" not in response.text

    monkeypatch.setenv("VLLM_OMNI_URL", "")
    importlib.reload(app_module)

    class FlakyClient:
        def __init__(self):
            self.calls = []

        async def chat(self, *args, **kwargs):
            normalized = dict(zip(("problem", "message", "history", "tts"), args))
            normalized.update(kwargs)
            kwargs = normalized
            self.calls.append(kwargs)
            if kwargs.get("stage") == "recognition":
                raise RuntimeError("upstream unavailable")
            return {"text": "已根据题图重新给出提示。", "audio_base64": None, "audio_mime": None}

    fake_client = FlakyClient()
    app_module.MINICPM_CLIENT = fake_client
    upstream_client = TestClient(app_module.app)
    recognized = upstream_client.post(
        "/api/recognize",
        files={"file": ("problem.png", _png_bytes(), "image/png")},
        data={"problem_text": "备用题面"},
    ).json()
    lesson = upstream_client.post(
        "/api/lesson",
        json={
            "session_id": recognized["session_id"],
            "problem": "备用题面",
            "message": "继续提示",
            "stage": "hint",
            "tts": False,
        },
    ).json()

    assert recognized["source"] == "mock"
    assert recognized["degraded"] is True
    assert "MiniCPM-o 识题暂不可用" in recognized["degraded_reason"]
    assert lesson["source"] == "minicpm"
    assert fake_client.calls[1]["image_bytes"] == fake_client.calls[0]["image_bytes"]

    monkeypatch.setenv("VLLM_OMNI_URL", "")
    importlib.reload(app_module)


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
    payload = response.json()
    assert payload["stage"] == "explain"
    assert payload["final_answer"] == "x = 6"


def test_explanation_prompt_requests_transferable_method():
    from teaching.minicpm_client import MiniCPMClient

    messages = MiniCPMClient._messages(
        "解方程：2x + 5 = 17。",
        "我已经完成一次尝试。",
        [],
        stage="explain",
    )
    prompt = messages[-1]["content"]
    if isinstance(prompt, list):
        prompt = prompt[0]["text"]
    assert "完整分步解析" in prompt
    assert "可迁移方法" in prompt
    assert "最终答案" in prompt


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


def test_minicpm_hint_advances_one_small_goal_and_extracts_student_question():
    from teaching.minicpm_client import MiniCPMClient, next_question_from_text

    messages = MiniCPMClient._messages("解方程：2x + 5 = 17。", "给我一个提示", [], "hint")
    prompt = messages[-1]["content"]
    assert "只推进一个小目标" in prompt
    assert "只提出一个具体问题" in prompt
    assert next_question_from_text("先观察等号两边。\n你觉得第一步应消去哪个数？") == "你觉得第一步应消去哪个数？"
    assert next_question_from_text("先观察已知条件。") == "你愿意先试着回答这个小问题吗？"


def test_minicpm_audio_turn_treats_attached_audio_as_student_input():
    from teaching.minicpm_client import MiniCPMClient

    messages = MiniCPMClient._messages(
        "解方程：2x + 5 = 17。",
        "根据学生的语音内容继续引导。",
        [],
        "hint",
        audio_base64="AAAAAA==",
        audio_sample_rate=16000,
    )
    content = messages[-1]["content"]
    assert "学生通过附带语音输入" in content[0]["text"]
    assert "以语音内容为准" in content[0]["text"]
    assert content[1]["type"] == "audio_url"
    assert content[1]["audio_url"]["url"].startswith("data:audio/wav;base64,")


def test_minicpm_stage_aware_timeout_defaults_and_override(monkeypatch):
    from teaching.minicpm_client import MiniCPMClient

    assert MiniCPMClient._timeout("recognition").read == 180
    assert MiniCPMClient._timeout("hint").read == 90
    monkeypatch.setenv("MINICPM_READ_TIMEOUT_SECONDS", "240")
    assert MiniCPMClient._timeout("recognition").read == 240


def test_minicpm_payload_enables_vllm_tts_template():
    from teaching.minicpm_client import MiniCPMClient

    adapter = MiniCPMClient("http://gpu.example.test:8099")
    payload = adapter._payload("题目", "朗读解释", [], True)
    assert payload["modalities"] == ["text", "audio"]
    assert payload["chat_template_kwargs"] == {"enable_thinking": False, "use_tts_template": True}


def test_all_subject_config_and_mock_lesson_contract(client):
    config = client.get("/api/config")
    assert config.status_code == 200
    subjects = config.json()["subjects"]
    assert [item["code"] for item in subjects] == [
        "chinese", "math", "english", "physics", "chemistry", "politics", "history", "geography", "biology"
    ]

    lesson = client.post(
        "/api/lesson",
        json={"subject": "history", "problem": "分析材料并说明工业革命的影响。", "stage": "hint"},
    )
    assert lesson.status_code == 200
    payload = lesson.json()
    assert payload["subject"] == "history"
    assert "历史" in payload["reply"]
    assert payload["final_answer"] is None


def test_subject_isolated_in_teaching_session(client):
    first = client.post(
        "/api/lesson",
        json={"subject": "english", "problem": "Explain the meaning of this sentence.", "stage": "hint"},
    ).json()
    second = client.post(
        "/api/lesson",
        json={
            "subject": "biology",
            "session_id": first["session_id"],
            "problem": "说明细胞膜的功能。",
            "stage": "hint",
        },
    ).json()
    assert first["subject"] == "english"
    assert second["subject"] == "biology"
    assert second["session_id"] != first["session_id"]


def test_non_math_practice_recommendation_keeps_subject(client):
    response = client.post(
        "/api/practice/recommend",
        json={"subject": "chemistry", "problem": "写出水分解的化学方程式。", "limit": 2},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["subject"] == "chemistry"
    assert len(payload["items"]) == 2
    assert all("化学" in item["problem"] for item in payload["items"])


def test_minicpm_payload_contains_subject_focus():
    from teaching.minicpm_client import MiniCPMClient

    payload = MiniCPMClient("http://gpu.example.test:8099")._payload(
        "分析材料", "给我提示", [], False, subject="history"
    )
    system = payload["messages"][0]["content"]
    assert "当前学科：历史" in system
    assert "时间线" in system


def test_lesson_request_defaults_to_text_only():
    from teaching.models import LessonRequest

    request = LessonRequest(problem="解方程：2x + 5 = 17。")
    assert request.tts is False


def test_speech_endpoint_generates_audio_without_lesson_context(client, monkeypatch):
    monkeypatch.setenv("VLLM_OMNI_URL", "http://upstream.example.test:8099")
    import app as app_module

    importlib.reload(app_module)

    class SpeechClient:
        model = "fake-minicpm"

        def __init__(self):
            self.calls = []

        async def chat(self, *args, **kwargs):
            normalized = dict(zip(("problem", "message", "history", "tts"), args))
            normalized.update(kwargs)
            self.calls.append(normalized)
            return {"text": normalized["problem"], "audio_base64": "UklGRg==", "audio_mime": "audio/wav"}

    fake_client = SpeechClient()
    app_module.MINICPM_CLIENT = fake_client
    upstream_client = TestClient(app_module.app)
    response = upstream_client.post(
        "/api/speech",
        json={"subject": "history", "text": "工业革命推动了生产力发展。"},
    )

    assert response.status_code == 200
    assert response.json() == {"audio_base64": "UklGRg==", "audio_mime": "audio/wav", "source": "minicpm"}
    assert fake_client.calls == [
        {
            "problem": "工业革命推动了生产力发展。",
            "message": "请原样朗读这段内容。",
            "history": [],
            "tts": True,
            "stage": "speech",
            "subject": "history",
        }
    ]

    monkeypatch.setenv("VLLM_OMNI_URL", "")
    importlib.reload(app_module)


def test_minicpm_sse_choice_events_support_text_and_audio():
    from teaching.minicpm_client import yield_from_events

    events = list(
        yield_from_events(
            {
                "choices": [{"delta": {"content": "分步"}}, {"delta": {"audio": {"data": "YWJj"}}}],
            }
        )
    )
    assert events == [
        {"type": "text_delta", "text_delta": "分步"},
        {"type": "audio_delta", "audio_data": "YWJj", "audio_mime": "audio/wav"},
    ]


def test_minicpm_streaming_audio_uses_content_with_modality_marker():
    from teaching.minicpm_client import yield_from_events

    events = list(
        yield_from_events(
            {"modality": "audio", "choices": [{"delta": {"content": "YWJj"}}]}
        )
    )
    assert events == [{"type": "audio_delta", "audio_data": "YWJj", "audio_mime": "audio/wav"}]


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


def test_remote_endpoint_is_default_when_upstream_not_overridden(monkeypatch):
    from teaching.minicpm_client import configured_client

    monkeypatch.delenv("VLLM_OMNI_URL", raising=False)
    monkeypatch.delenv("MINICPM_GATEWAY_URL", raising=False)
    configured = configured_client()
    assert configured is not None
    assert configured.base_url == "https://minicpm45.duckcloud.fun/v1"
    assert configured.model == "/tmp/pretrainmodel/MiniCPM-o-4_5"


def test_model_endpoint_can_be_changed_from_single_config_file(tmp_path, monkeypatch):
    from teaching.minicpm_client import configured_client

    config_path = tmp_path / "minicpm.json"
    config_path.write_text(
        '{"base_url":"https://replacement.example.test/v1","model":"replacement-model"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("MINICPM_CONFIG_FILE", str(config_path))
    monkeypatch.delenv("VLLM_OMNI_URL", raising=False)
    monkeypatch.delenv("MINICPM_GATEWAY_URL", raising=False)
    monkeypatch.delenv("MINICPM_MODEL", raising=False)
    configured = configured_client()
    assert configured is not None
    assert configured.base_url == "https://replacement.example.test/v1"
    assert configured.model == "replacement-model"


def test_model_config_rejects_embedded_credentials(tmp_path, monkeypatch):
    config_path = tmp_path / "minicpm.json"
    config_path.write_text(
        '{"base_url":"https://user:pass@example.test/v1","model":"model"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("MINICPM_CONFIG_FILE", str(config_path))
    monkeypatch.delenv("VLLM_OMNI_URL", raising=False)
    monkeypatch.delenv("MINICPM_GATEWAY_URL", raising=False)
    from teaching.model_config import load_model_config

    with pytest.raises(RuntimeError, match="不应包含凭据"):
        load_model_config()


def test_model_config_loads_api_key_from_configured_env(tmp_path, monkeypatch):
    config_path = tmp_path / "minicpm.json"
    config_path.write_text(
        '{"base_url":"https://model.example.test/v1","model":"model","api_key_env":"CUSTOM_MINICPM_KEY"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("MINICPM_CONFIG_FILE", str(config_path))
    monkeypatch.setenv("CUSTOM_MINICPM_KEY", "x" * 32)
    monkeypatch.delenv("MINICPM_API_KEY", raising=False)
    from teaching.model_config import load_model_config

    assert load_model_config()["api_key"] == "x" * 32


def test_minicpm_client_sends_bearer_api_key():
    from teaching.minicpm_client import MiniCPMClient

    client = MiniCPMClient(
        "https://model.example.test/v1",
        "model",
        api_key="k" * 32,
    )
    assert client._request_headers()["Authorization"] == f"Bearer {'k' * 32}"


def test_public_config_does_not_expose_upstream_endpoint(client):
    payload = client.get("/api/config").json()
    assert payload["gateway_url"] == ""


def test_api_docs_are_disabled_by_default(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_cors_rejects_wildcard_with_credentials(monkeypatch):
    monkeypatch.setenv("MATH_COACH_ALLOWED_ORIGINS", "*")
    from app import _allowed_origins

    with pytest.raises(RuntimeError, match="cannot use '\\*'" ):
        _allowed_origins()


def test_rate_limiter_ignores_forwarded_header_unless_proxy_is_trusted(monkeypatch):
    from teaching.security import RateLimitMiddleware

    scope = {
        "type": "http",
        "client": ("10.0.0.1", 12345),
        "headers": [(b"x-forwarded-for", b"1.1.1.1, 2.2.2.2")],
    }
    request = Request(scope)
    monkeypatch.setenv("MATH_COACH_TRUST_PROXY_HEADERS", "false")
    assert RateLimitMiddleware(None)._client_key(request) == "10.0.0.1"

    monkeypatch.setenv("MATH_COACH_TRUST_PROXY_HEADERS", "true")
    assert RateLimitMiddleware(None)._client_key(request) == "2.2.2.2"


def test_spa_fallback_rejects_path_traversal():
    from pathlib import Path

    from app import _static_file

    base = Path(__file__).resolve().parent
    assert _static_file(base, "../conftest.py") is None


def test_image_upload_rejects_declared_mime_mismatch(client, monkeypatch):
    monkeypatch.setenv("VLLM_OMNI_URL", "http://upstream.example.test:8099")
    import app as app_module

    importlib.reload(app_module)
    upstream_client = TestClient(app_module.app)
    response = upstream_client.post(
        "/api/recognize",
        files={"file": ("problem.png", b"not-a-png", "image/png")},
        data={"problem_text": "3x = 12"},
    )
    assert response.status_code == 415

    monkeypatch.setenv("VLLM_OMNI_URL", "")
    importlib.reload(app_module)


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


def test_recognition_parser_extracts_truncated_json_and_formats_math():
    from teaching.recognition import parse_recognition

    payload = json.dumps(
        {
            "problem": (
                "图片中的初中数学题识别如下：\n计算 "
                r"\(\left(\sqrt{\frac{5}{2}}+1\right)\times\sqrt{\frac{5}{2}+1}\)"
                " 的结果为（　　）\nA. 0"
            ),
            "annotations": [{"label": "题目区域", "x": 0.1}],
        },
        ensure_ascii=False,
    )
    truncated = f"```json\n{payload[:-12]}"
    problem, annotations = parse_recognition(truncated)
    assert problem == "计算 (√((5)/(2))+1)×√((5)/(2)+1) 的结果为（　　）\nA. 0"
    assert annotations == []


def test_recognition_parser_never_falls_back_to_raw_json():
    from teaching.recognition import parse_recognition

    problem, annotations = parse_recognition('{"unknown":"value"}')
    assert problem == ""
    assert annotations == []


def test_recognition_parser_extracts_multiple_truncated_problems():
    from teaching.recognition import parse_recognition_items

    truncated = (
        '```json\n{"problems":[{"problem":"第一题：2x + 5 = 17"},'
        '{"problem":"第二题：3x - 4 = 11"},{"problem":"第三题：'
    )
    items = parse_recognition_items(truncated)
    assert [item.problem for item in items] == ["第一题：2x + 5 = 17", "第二题：3x - 4 = 11"]


def test_recognition_parser_splits_combined_numbered_page():
    from teaching.recognition import parse_recognition_items

    combined = """B 规律方法综合练
12. 计算（√(5)/2 + 1）× √(5)/2 + 1 的结果为（　　）
A. 0　B. 1　C. 2　D. √(5) - 1/2
13. 计算：(√5 - 2)^2025 × (√5 + 2)^2024 =
14. 计算：(1) 2(√5 - √27)(3√3 + √20)
15. 已知 x=(√7 - √5)/2，y=(√7 + √5)/2，求值。
(1) x+y；
(2) xy；
(3) x/y + y/x。
16. 利用有理化因式计算 1/√2。"""
    items = parse_recognition_items(json.dumps({"problem": combined}, ensure_ascii=False))
    assert len(items) == 5
    assert [item.problem.split(".", 1)[0] for item in items] == ["12", "13", "14", "15", "16"]
    assert "(1) x+y" in items[3].problem
    assert "(3) x/y + y/x" in items[3].problem


def test_recognition_parser_splits_numbered_problems_without_spaces():
    from teaching.recognition import parse_recognition_items

    combined = """1、解方程 2x+5=17
2．计算 √5×√5
3.求三角形面积"""
    items = parse_recognition_items(json.dumps({"problem": combined}, ensure_ascii=False))

    assert [item.problem for item in items] == [
        "1、解方程 2x+5=17",
        "2．计算 √5×√5",
        "3.求三角形面积",
    ]


def test_standard_screenshot_retries_tiles_when_whole_image_returns_one_problem(client, monkeypatch):
    output = io.BytesIO()
    image = Image.new("RGB", (720, 1280), "white")
    image.save(output, format="PNG")

    class ScreenshotClient:
        def __init__(self):
            self.calls = 0

        async def chat(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                problems = [{"problem": "1、第一题"}]
            elif self.calls == 2:
                problems = [{"problem": "1、第一题"}]
            else:
                problems = [{"problem": "2、第二题"}]
            return {"text": json.dumps({"problems": problems}, ensure_ascii=False)}

    import app as app_module

    fake_client = ScreenshotClient()
    monkeypatch.setattr(app_module, "MINICPM_CLIENT", fake_client)
    response = client.post(
        "/api/recognize",
        files={"file": ("problems.png", output.getvalue(), "image/png")},
    )

    assert response.status_code == 200
    assert [item["problem"] for item in response.json()["problems"]] == ["1、第一题", "2、第二题"]
    assert fake_client.calls == 3


def test_dense_image_recognizes_multiple_problems_with_vertical_retry(client, monkeypatch):
    output = io.BytesIO()
    image = Image.new("RGB", (1000, 2600), "white")
    for row in range(300, 2300, 200):
        for column in range(100, 900, 20):
            image.putpixel((column, row), (0, 0, 0))
    image.save(output, format="PNG")

    class DensePageClient:
        async def chat(self, **kwargs):
            prepared = Image.open(io.BytesIO(kwargs["image_bytes"]))
            if prepared.width < 700:
                text = json.dumps({"problems": [{"problem": "1. first equation"}]}, ensure_ascii=False)
            else:
                text = json.dumps(
                    {"problems": [{"problem": "1. first equation"}, {"problem": "2. second equation"}]},
                    ensure_ascii=False,
                )
            return {"text": text}

    import app as app_module

    monkeypatch.setattr(app_module, "MINICPM_CLIENT", DensePageClient())
    response = client.post(
        "/api/recognize",
        files={"file": ("problems.png", output.getvalue(), "image/png")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert [item["problem"] for item in payload["problems"]] == [
        "1. first equation",
        "2. second equation",
    ]


def test_recognition_parser_converts_plain_sqrt_notation():
    from teaching.recognition import parse_recognition

    problem, _ = parse_recognition("Compute (sqrt(5) + 1/SQRT5)")
    assert problem == "Compute (√(5) + 1/√5)"


def test_recognition_parser_converts_superscript_without_error():
    from teaching.recognition import parse_recognition

    problem, _ = parse_recognition("计算 (√5)^2025 × (√5)^2024")
    assert problem == "计算 (√5)²⁰²⁵ × (√5)²⁰²⁴"


def test_confirm_stage_is_accepted_as_hint(client):
    response = client.post(
        "/api/lesson",
        json={"problem": "矩形长 6，宽 4，求面积。", "message": "确认题面", "stage": "confirm"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["final_answer"] is None
    assert payload["reply"]


def test_mock_hint_does_not_leak_answer_in_locked_steps(client):
    response = client.post(
        "/api/lesson",
        json={"problem": "解方程：2x + 5 = 17。", "message": "给一个提示", "stage": "hint", "tts": False},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["final_answer"] is None
    assert all(step["body"] != "所以 x = 6。" for step in payload["steps"])


def test_teaching_session_is_bound_to_owner():
    from datetime import datetime, timedelta, timezone

    from teaching.orchestrator import TeachingOrchestrator

    orchestrator = TeachingOrchestrator()
    first = orchestrator.get_or_create(None, "题目", "user-a")
    hijacked = orchestrator.get_or_create(first.id, "题目", "user-b")
    assert hijacked.id != first.id
    assert orchestrator.delete(first.id, "user-b") is False
    assert orchestrator.delete(first.id, "user-a") is True


def test_recognition_session_image_expires_after_thirty_minutes():
    from datetime import datetime, timedelta, timezone

    from teaching.orchestrator import TeachingOrchestrator

    orchestrator = TeachingOrchestrator()
    session = orchestrator.create_recognition_session("题面", "user-a", b"image", "image/png")
    session.touched_at = datetime.now(timezone.utc) - timedelta(minutes=31)
    replacement = orchestrator.get_or_create(session.id, "题面", "user-a")
    assert replacement.id != session.id
    assert replacement.image_bytes is None
