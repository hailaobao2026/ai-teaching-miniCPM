from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from teaching.auth_store import AUTH_STORE, resolve_backend, verify_password
from teaching.deps import require_admin, require_user
from teaching.minicpm_client import configured_client, merge_audio, structured_steps
from teaching.mock_tutor import EXAMPLES, lesson as mock_lesson, recognize as mock_recognize
from teaching.models import FeedbackRequest, LessonRequest, LessonResponse, RecognizeResponse
from teaching.orchestrator import TeachingOrchestrator
from teaching.rbac import GRADE_LABELS, ROLES, public_user, validate_register_payload
from teaching.recognition import parse_recognition


ROOT = Path(__file__).parent
FRONTEND_DIST = ROOT / "frontend" / "dist"
STATIC_DIR = ROOT / "static"
MINICPM_CLIENT = configured_client()
ORCHESTRATOR = TeachingOrchestrator()
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "MATH_COACH_ALLOWED_ORIGINS",
        "http://127.0.0.1:8080,http://localhost:8080,http://127.0.0.1:8081,http://localhost:8081,http://127.0.0.1:3000,http://localhost:3000",
    ).split(",")
    if origin.strip()
]
# Teaching APIs require login by default, matching video-platform auth style.

def auth_required() -> bool:
    return str(os.getenv("MATH_COACH_AUTH_REQUIRED", "true")).lower() not in {"0", "false", "no"}

app = FastAPI(title="MiniCPM Math Coach", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str
    nickname: str
    role: str = "student"
    grade: str | None = None


class ProfileUpdateRequest(BaseModel):
    nickname: str | None = None
    grade: str | None = None


class AdminUserUpdateRequest(BaseModel):
    role: str | None = None
    status: str | None = None
    nickname: str | None = None
    password: str | None = None


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _model_dump(model: LessonResponse) -> dict:
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    value = authorization.strip()
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return value or None


def _current_user_optional(authorization: str | None = Header(default=None)) -> dict[str, Any] | None:
    token = _bearer_token(authorization)
    user = AUTH_STORE.get_session_user(token)
    if user and (user.get("status") or "active") != "active":
        return None
    return user


def _current_user_required(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    if not auth_required():
        user = _current_user_optional(authorization)
        if user:
            return user
        # Anonymous fallback only when auth is explicitly disabled.
        return {
            "id": "anonymous",
            "email": "anonymous@local",
            "nickname": "访客",
            "role": ROLES["STUDENT"],
            "status": "active",
        }
    return require_user(authorization)


@app.get("/api/health")
async def health() -> dict[str, str | bool]:
    info = AUTH_STORE.backend_info()
    return {
        "ok": True,
        "mode": "minicpm" if MINICPM_CLIENT else "mock",
        "upstream_configured": bool(MINICPM_CLIENT),
        "auth_required": auth_required(),
        "db_backend": info.get("backend", resolve_backend()),
    }


@app.get("/api/config")
async def config() -> dict[str, Any]:
    return {
        "mode": "minicpm" if MINICPM_CLIENT else "mock",
        "model": os.getenv("MINICPM_MODEL", "openbmb/MiniCPM-o-4_5"),
        "gateway_url": os.getenv("VLLM_OMNI_URL", "") or os.getenv("MINICPM_GATEWAY_URL", ""),
        "provider": "vllm-omni" if MINICPM_CLIENT else "mock",
        "mvp_mode": "turn-based",
        "auth_required": auth_required(),
        "roles": [ROLES["STUDENT"], ROLES["TEACHER"], ROLES["ADMIN"]],
        "grades": [{"code": code, "name": GRADE_LABELS[code]} for code in GRADE_LABELS],
        "demo_accounts": [
            {"id": "admin", "label": "管理员", "email": os.getenv("ADMIN_EMAIL", "teacher@demo.local")},
            {"id": "teacher", "label": "教师", "email": os.getenv("DEMO_TEACHER_EMAIL", "math.teacher@demo.local")},
            {"id": "student", "label": "学生", "email": os.getenv("DEMO_STUDENT_EMAIL", "student@demo.local")},
        ],
    }


@app.post("/api/auth/register")
async def register(request: RegisterRequest) -> dict[str, Any]:
    checked = validate_register_payload(request.model_dump() if hasattr(request, "model_dump") else request.dict())
    if not checked["ok"]:
        raise HTTPException(status_code=400, detail=checked["error"])
    value = checked["value"]
    try:
        user = AUTH_STORE.create_user(
            email=value["email"],
            password=value["password"],
            nickname=value["nickname"],
            role=value["role"],
            grade=value.get("grade"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    token = AUTH_STORE.create_session(user["id"])
    return {"token": token, "user": public_user(user)}


@app.post("/api/auth/login")
async def login(request: LoginRequest) -> dict[str, Any]:
    email = str(request.email or "").strip().lower()
    password = str(request.password or "")
    user = AUTH_STORE.find_user_by_email(email)
    if not user or not verify_password(password, user.get("password_hash")):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    if (user.get("status") or "active") != "active":
        raise HTTPException(status_code=401, detail="账号已禁用")
    token = AUTH_STORE.create_session(user["id"])
    return {"token": token, "user": public_user(user)}


@app.get("/api/auth/me")
async def me(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return {"user": public_user(user)}


@app.post("/api/auth/logout")
async def logout(authorization: str | None = Header(default=None)) -> dict[str, bool]:
    AUTH_STORE.delete_session(_bearer_token(authorization))
    return {"ok": True}


@app.patch("/api/me/profile")
async def update_profile(
    request: ProfileUpdateRequest,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    try:
        updated = AUTH_STORE.update_profile(
            user["id"],
            nickname=request.nickname,
            grade=request.grade,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"user": public_user(updated)}


@app.get("/api/admin/stats")
async def admin_stats(_admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    stats = AUTH_STORE.stats()
    stats["mode"] = "minicpm" if MINICPM_CLIENT else "mock"
    stats["upstream_configured"] = bool(MINICPM_CLIENT)
    return stats


@app.get("/api/admin/users")
async def admin_list_users(
    role: str | None = None,
    status: str | None = None,
    q: str | None = None,
    page: int = 1,
    limit: int = 50,
    _admin: dict[str, Any] = Depends(require_admin),
) -> list[dict[str, Any]]:
    return AUTH_STORE.list_users(role=role, status=status, query=q, page=page, limit=limit)


@app.patch("/api/admin/users/{user_id}")
async def admin_update_user(
    user_id: str,
    request: AdminUserUpdateRequest,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    if user_id == admin.get("id") and request.status == "disabled":
        raise HTTPException(status_code=400, detail="不能禁用当前登录的管理员")
    if user_id == admin.get("id") and request.role and request.role != ROLES["ADMIN"]:
        raise HTTPException(status_code=400, detail="不能取消当前管理员角色")
    try:
        updated = AUTH_STORE.update_user_admin(
            user_id,
            role=request.role,
            status=request.status,
            nickname=request.nickname,
            password=request.password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"user": public_user(updated)}


@app.get("/api/examples")
async def examples(_user: dict[str, Any] = Depends(_current_user_required)) -> list[dict[str, str]]:
    return EXAMPLES


@app.post("/api/recognize", response_model=RecognizeResponse)
async def recognize(
    file: UploadFile | None = File(default=None),
    problem_text: str = Form(default=""),
    _user: dict[str, Any] = Depends(_current_user_required),
) -> RecognizeResponse:
    """Recognize a problem. Real image understanding is delegated to upstream when configured."""
    if not MINICPM_CLIENT:
        return mock_recognize(problem_text)
    if not file:
        return mock_recognize(problem_text)
    if file.content_type not in {"image/png", "image/jpeg", "image/webp"}:
        return mock_recognize(problem_text)
    image_bytes = await file.read()
    if not image_bytes or len(image_bytes) > 8 * 1024 * 1024:
        return mock_recognize(problem_text)
    try:
        result = await MINICPM_CLIENT.chat(
            problem="请识别图片中的初中数学题。",
            message='只返回 JSON：{"problem":"可编辑题面","annotations":[{"label":"题目区域","x":0,"y":0,"width":1,"height":1}]}。坐标是相对图片宽高的 0 到 1 小数；无法定位时 annotations 返回空数组。不要解题。',
            history=[],
            tts=False,
            image_bytes=image_bytes,
            image_mime=file.content_type or "image/png",
        )
        text, annotations = parse_recognition(result["text"] or problem_text)
        response = mock_recognize(text)
        response.source = "minicpm"
        response.annotations = annotations
        return response
    except Exception:
        return mock_recognize(problem_text)


@app.post("/api/lesson", response_model=LessonResponse)
async def lesson(
    request: LessonRequest,
    _user: dict[str, Any] = Depends(_current_user_required),
) -> LessonResponse:
    session = ORCHESTRATOR.get_or_create(request.session_id, request.problem)
    if not MINICPM_CLIENT:
        response = mock_lesson(session.problem, request.message, request.stage)
        response.session_id = session.id
        ORCHESTRATOR.commit(session, request.message, response.reply, request.stage)
        return response
    try:
        result = await MINICPM_CLIENT.chat(
            session.problem,
            request.message,
            session.history,
            request.tts,
            audio_base64=request.audio_base64,
            audio_sample_rate=request.audio_sample_rate,
        )
        text = result["text"] or "模型没有返回可读内容，请重试。"
        steps, parsed_answer = structured_steps(text)
        response = LessonResponse(
            session_id=session.id,
            reply=text,
            steps=steps or mock_lesson(session.problem, request.message, request.stage).steps,
            final_answer=parsed_answer if request.stage == "explain" else None,
            next_question="你还卡在哪一步？可以继续追问。",
            confidence=0.72,
            source="minicpm",
            audio_base64=result.get("audio_base64"),
            audio_mime=result.get("audio_mime"),
        )
        ORCHESTRATOR.commit(session, request.message, text, request.stage)
        return response
    except Exception as exc:
        response = mock_lesson(session.problem, request.message, request.stage)
        response.session_id = session.id
        response.reply = f"上游暂时不可用，已切换演示讲解。原因：{exc}"
        ORCHESTRATOR.commit(session, request.message, response.reply, request.stage)
        return response


@app.post("/api/lesson/stream")
async def lesson_stream(
    request: LessonRequest,
    _user: dict[str, Any] = Depends(_current_user_required),
) -> StreamingResponse:
    session = ORCHESTRATOR.get_or_create(request.session_id, request.problem)

    async def event_generator():
        yield _sse({"type": "session", "session_id": session.id})
        if not MINICPM_CLIENT:
            response = mock_lesson(session.problem, request.message, request.stage)
            response.session_id = session.id
            text = response.reply or ""
            chunk_size = max(8, len(text) // 6 or 8)
            for index in range(0, len(text), chunk_size):
                yield _sse({"type": "text_delta", "text_delta": text[index : index + chunk_size]})
                await asyncio.sleep(0.01)
            ORCHESTRATOR.commit(session, request.message, response.reply, request.stage)
            yield _sse({"type": "lesson", "lesson": _model_dump(response)})
            yield _sse({"type": "done"})
            return

        chunks: list[str] = []
        audio_parts: list[str] = []
        try:
            async for event in MINICPM_CLIENT.stream(
                session.problem,
                request.message,
                session.history,
                request.tts,
                audio_base64=request.audio_base64,
                audio_sample_rate=request.audio_sample_rate,
            ):
                if event.get("type") == "text_delta" and event.get("text_delta"):
                    chunks.append(event["text_delta"])
                    yield _sse({"type": "text_delta", "text_delta": event["text_delta"]})
                elif event.get("type") == "audio_delta" and event.get("audio_data"):
                    audio_parts.append(event["audio_data"])
            text = "".join(chunks) or "模型没有返回可读内容，请重试。"
            steps, parsed_answer = structured_steps(text)
            response = LessonResponse(
                session_id=session.id,
                reply=text,
                steps=steps or mock_lesson(session.problem, request.message, request.stage).steps,
                final_answer=parsed_answer if request.stage == "explain" else None,
                next_question="你还卡在哪一步？可以继续追问。",
                confidence=0.72,
                source="minicpm",
                audio_base64=merge_audio(audio_parts) if audio_parts else None,
                audio_mime="audio/wav" if audio_parts else None,
            )
            ORCHESTRATOR.commit(session, request.message, text, request.stage)
            yield _sse({"type": "lesson", "lesson": _model_dump(response)})
            yield _sse({"type": "done"})
        except Exception as exc:
            response = mock_lesson(session.problem, request.message, request.stage)
            response.session_id = session.id
            response.reply = f"上游暂时不可用，已切换演示讲解。原因：{exc}"
            if response.reply:
                yield _sse({"type": "text_delta", "text_delta": response.reply})
            ORCHESTRATOR.commit(session, request.message, response.reply, request.stage)
            yield _sse({"type": "lesson", "lesson": _model_dump(response)})
            yield _sse({"type": "done"})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/feedback")
async def feedback(
    request: FeedbackRequest,
    _user: dict[str, Any] = Depends(_current_user_required),
) -> dict[str, str]:
    return {"status": "accepted", "message": "反馈已记录，谢谢。"}


@app.delete("/api/session/{session_id}")
async def delete_session(
    session_id: str,
    _user: dict[str, Any] = Depends(_current_user_required),
) -> dict[str, bool]:
    return {"deleted": bool(ORCHESTRATOR.delete(session_id))}


def _frontend_index() -> Path:
    dist_index = FRONTEND_DIST / "index.html"
    if dist_index.exists():
        return dist_index
    return STATIC_DIR / "index.html"


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(_frontend_index())


if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="frontend-assets")

# Legacy static assets (vanilla fallback) and any non-hashed files.
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str) -> FileResponse:
    """Serve Vite SPA assets/fallback without shadowing API/docs routes."""
    blocked_prefixes = ("api/", "docs", "redoc", "openapi.json")
    if full_path == "api" or full_path.startswith(blocked_prefixes):
        raise HTTPException(status_code=404, detail="Not Found")
    candidate = FRONTEND_DIST / full_path
    if candidate.is_file():
        return FileResponse(candidate)
    static_candidate = STATIC_DIR / full_path
    if static_candidate.is_file():
        return FileResponse(static_candidate)
    return FileResponse(_frontend_index())
