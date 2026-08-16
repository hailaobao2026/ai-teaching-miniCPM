from __future__ import annotations

import asyncio
import io
import json
import re
import os
import logging
from urllib.parse import urlparse
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from teaching.answers import answers_equivalent
from teaching.auth_store import AUTH_STORE, NotebookConflictError, resolve_backend, verify_password
from teaching.deps import (
    cookie_name,
    cookie_samesite,
    cookie_secure,
    extract_token,
    require_admin,
    require_user,
    session_ttl_seconds,
)
from teaching.security import RateLimitMiddleware, SecurityHeadersMiddleware
from teaching.minicpm_client import configured_client, merge_audio, next_question_from_text, structured_steps
from teaching.mock_tutor import EXAMPLES, lesson as mock_lesson, recognize as mock_recognize
from teaching.models import (
    Annotation,
    FeedbackRequest,
    LessonRequest,
    LessonResponse,
    NotebookAttemptRequest,
    PracticeRecommendRequest,
    RecognizeResponse,
    RecognizedProblem,
    SpeechRequest,
    SpeechResponse,
)
from teaching.practice import (
    classify_topic,
    normalize_problem,
    practice_bank,
    recommend_practice,
    topic_label,
)
from teaching.orchestrator import TeachingOrchestrator
from teaching.rbac import GRADE_LABELS, ROLES, public_user, validate_register_payload
from teaching.recognition import parse_recognition_items
from teaching.subjects import normalize_subject, subject_info, subject_name, SUBJECT_FOCUS


ROOT = Path(__file__).parent
LOGGER = logging.getLogger(__name__)
FRONTEND_DIST = ROOT / "frontend" / "dist"
STATIC_DIR = ROOT / "static"
MINICPM_CLIENT = configured_client()
ORCHESTRATOR = TeachingOrchestrator()


def _allowed_origins() -> list[str]:
    raw = os.getenv(
        "MATH_COACH_ALLOWED_ORIGINS",
        "http://127.0.0.1:8080,http://localhost:8080,http://127.0.0.1:8081,http://localhost:8081,http://127.0.0.1:3000,http://localhost:3000",
    )
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    for origin in origins:
        if origin == "*":
            raise RuntimeError("MATH_COACH_ALLOWED_ORIGINS cannot use '*' with credentials")
        parsed = urlparse(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError(f"Invalid MATH_COACH_ALLOWED_ORIGINS entry: {origin}")
        if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
            raise RuntimeError(f"MATH_COACH_ALLOWED_ORIGINS must contain origins only: {origin}")
    return origins


ALLOWED_ORIGINS = _allowed_origins()
# Teaching APIs require login by default, matching video-platform auth style.

def auth_required() -> bool:
    return str(os.getenv("MATH_COACH_AUTH_REQUIRED", "true")).lower() not in {"0", "false", "no"}

app = FastAPI(
    title="MiniCPM All-Subject Coach",
    version="0.2.0",
    docs_url="/docs" if str(os.getenv("MATH_COACH_ENABLE_DOCS", "false")).lower() in {"1", "true", "yes", "on"} else None,
    redoc_url="/redoc" if str(os.getenv("MATH_COACH_ENABLE_DOCS", "false")).lower() in {"1", "true", "yes", "on"} else None,
    openapi_url="/openapi.json" if str(os.getenv("MATH_COACH_ENABLE_DOCS", "false")).lower() in {"1", "true", "yes", "on"} else None,
)
# Middleware order: last added runs first on request.
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
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


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=cookie_name(),
        value=token,
        max_age=session_ttl_seconds(),
        httponly=True,
        secure=cookie_secure(),
        samesite=cookie_samesite(),
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=cookie_name(),
        path="/",
        httponly=True,
        secure=cookie_secure(),
        samesite=cookie_samesite(),
    )


def _current_user_optional(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any] | None:
    token = extract_token(request, authorization)
    user = AUTH_STORE.get_session_user(token)
    if user and (user.get("status") or "active") != "active":
        return None
    return user


def _current_user_required(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    if not auth_required():
        user = _current_user_optional(request, authorization)
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
    return require_user(request, authorization)


def _verify_image(image_bytes: bytes, declared_mime: str) -> None:
    from PIL import Image

    expected_formats = {
        "image/png": "PNG",
        "image/jpeg": "JPEG",
        "image/webp": "WEBP",
    }
    try:
        image = Image.open(io.BytesIO(image_bytes))
        if image.format != expected_formats[declared_mime]:
            raise ValueError("image format mismatch")
        width, height = image.size
        if width < 1 or height < 1 or width > 10000 or height > 10000 or width * height > 20_000_000:
            raise ValueError("image dimensions exceed limits")
        image.verify()
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=415, detail="图片内容无效或超出尺寸限制") from exc


def _vision_limits() -> tuple[int, int]:
    max_edge = int(os.getenv("MINICPM_VISION_MAX_EDGE", "1280"))
    quality = int(os.getenv("MINICPM_VISION_JPEG_QUALITY", "90"))
    return min(max(max_edge, 640), 2048), min(max(quality, 60), 95)


def _prepare_vision_image(image_bytes: bytes, declared_mime: str) -> tuple[bytes, str]:
    from PIL import Image, ImageOps

    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
        image = ImageOps.exif_transpose(image)
        if image.mode in {"RGBA", "LA"}:
            alpha = image.getchannel("A")
            flattened = Image.new("RGB", image.size, "white")
            flattened.paste(image.convert("RGB"), mask=alpha)
            image = flattened
        elif image.mode != "RGB":
            image = image.convert("RGB")
        max_edge, quality = _vision_limits()
        if max(image.size) > max_edge:
            scale = max_edge / max(image.size)
            image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=quality, optimize=True, progressive=True)
        return output.getvalue(), "image/jpeg"
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=415, detail="图片内容无效或无法压缩") from exc


def _vertical_retry_tiles(image_bytes: bytes, declared_mime: str) -> list[tuple[bytes, int, int, int]]:
    """Split a page when whole-image recognition may have stopped after the first problem."""
    from PIL import Image, ImageOps, ImageStat

    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
        image = ImageOps.exif_transpose(image).convert("RGB")
        max_edge, _ = _vision_limits()
        if image.height < min(max_edge, 1024):
            return []

        grayscale = image.convert("L")
        middle = image.height // 2
        window = max(1, image.height // 16)
        split = min(
            range(max(1, middle - window), min(image.height - 1, middle + window + 1)),
            key=lambda row: ImageStat.Stat(grayscale.crop((0, row, image.width, row + 1))).stddev[0],
        )
        overlap = max(16, image.height // 25)
        top = image.crop((0, 0, image.width, min(image.height, split + overlap)))
        bottom = image.crop((0, max(0, split - overlap), image.width, image.height))
        tiles: list[tuple[Image.Image, int]] = [(top, 0), (bottom, max(0, split - overlap))]
        prepared: list[tuple[bytes, int, int, int]] = []
        for tile, offset in tiles:
            tile_bytes, _ = _encode_and_prepare_vision_image(tile)
            prepared.append((tile_bytes, offset, image.height, tile.height))
        return prepared
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=415, detail="图片内容无效或无法分块") from exc


def _encode_and_prepare_vision_image(image: object) -> tuple[bytes, str]:
    output = io.BytesIO()
    image.save(output, format="PNG")
    return _prepare_vision_image(output.getvalue(), "image/png")


def _remap_tile_annotations(items: list[RecognizedProblem], offset: int, source_height: int, tile_height: int) -> None:
    scale = tile_height / source_height
    for item in items:
        for annotation in item.annotations:
            annotation.y = min(1.0, (offset + annotation.y * tile_height) / source_height)
            annotation.height = min(1.0 - annotation.y, annotation.height * scale)


def _unique_problems(items: list[RecognizedProblem]) -> list[RecognizedProblem]:
    from difflib import SequenceMatcher

    unique: list[RecognizedProblem] = []
    unique_normalized: list[str] = []
    for item in items:
        normalized = re.sub(r"\s+", "", item.problem).casefold()
        if any(SequenceMatcher(None, normalized, existing).ratio() >= 0.92 for existing in unique_normalized if existing):
            continue
        unique.append(item)
        unique_normalized.append(normalized)
    return unique


def _render_pdf_pages(pdf_bytes: bytes) -> list[bytes]:
    import pypdfium2 as pdfium

    document = None
    pages: list = []
    bitmaps: list = []
    rendered: list[bytes] = []
    try:
        document = pdfium.PdfDocument(pdf_bytes)
        if not 1 <= len(document) <= 20:
            raise ValueError("invalid page count")
        for page_number in range(len(document)):
            page = document[page_number]
            pages.append(page)
            width, height = page.get_size()
            if width <= 0 or height <= 0 or width > 10000 or height > 10000:
                raise ValueError("invalid page size")
            scale = min(2.0, (20_000_000 / (width * height)) ** 0.5)
            bitmap = page.render(scale=scale)
            bitmaps.append(bitmap)
            image = bitmap.to_pil()
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="PNG", optimize=True)
            rendered.append(output.getvalue())
        return rendered
    except Exception as exc:
        raise HTTPException(status_code=415, detail="PDF 内容无效或超出页数限制") from exc
    finally:
        for bitmap in bitmaps:
            bitmap.close()
        for page in pages:
            page.close()
        if document:
            document.close()


def _render_pdf_first_page(pdf_bytes: bytes) -> bytes:
    return _render_pdf_pages(pdf_bytes)[0]


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
        "model": MINICPM_CLIENT.model if MINICPM_CLIENT else "mock",
        "gateway_url": "",
        "provider": "vllm-omni" if MINICPM_CLIENT else "mock",
        "mvp_mode": "turn-based",
        "auth_required": auth_required(),
        "roles": [ROLES["STUDENT"], ROLES["TEACHER"], ROLES["ADMIN"]],
        "grades": [{"code": code, "name": GRADE_LABELS[code]} for code in GRADE_LABELS],
        "demo_accounts": _demo_account_hints(),
        "cookie_auth": True,
        "subjects": subject_info(),
    }


def _demo_account_hints() -> list[dict[str, str]]:
    """Expose demo emails only when seeding is explicitly enabled (never passwords)."""
    seed = str(os.getenv("SEED_DEMO_ACCOUNTS", "false")).lower() in {"1", "true", "yes", "on"}
    if not seed:
        return []
    return [
        {"id": "admin", "label": "管理员", "email": os.getenv("ADMIN_EMAIL", "admin@example.com")},
        {
            "id": "teacher",
            "label": "教师",
            "email": os.getenv("DEMO_TEACHER_EMAIL", "math.teacher@example.local"),
        },
        {
            "id": "student",
            "label": "学生",
            "email": os.getenv("DEMO_STUDENT_EMAIL", "student@example.local"),
        },
    ]


@app.post("/api/auth/register")
async def register(body: RegisterRequest, response: Response) -> dict[str, Any]:
    checked = validate_register_payload(body.model_dump() if hasattr(body, "model_dump") else body.dict())
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
    _set_session_cookie(response, token)
    return {"user": public_user(user), "cookie_auth": True}


@app.post("/api/auth/login")
async def login(body: LoginRequest, response: Response) -> dict[str, Any]:
    email = str(body.email or "").strip().lower()
    password = str(body.password or "")
    user = AUTH_STORE.find_user_by_email(email)
    if not user or not verify_password(password, user.get("password_hash")):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    if (user.get("status") or "active") != "active":
        raise HTTPException(status_code=401, detail="账号已禁用")
    token = AUTH_STORE.create_session(user["id"])
    _set_session_cookie(response, token)
    return {"user": public_user(user), "cookie_auth": True}


@app.get("/api/auth/me")
async def me(user: dict[str, Any] = Depends(_current_user_required)) -> dict[str, Any]:
    return {"user": public_user(user)}


@app.post("/api/auth/logout")
async def logout(
    request: Request,
    response: Response,
    authorization: str | None = Header(default=None),
) -> dict[str, bool]:
    AUTH_STORE.delete_session(extract_token(request, authorization))
    _clear_session_cookie(response)
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
    problem_text: str = Form(default="", max_length=4000),
    subject: str = Form(default="math", max_length=32),
    _user: dict[str, Any] = Depends(_current_user_required),
) -> RecognizeResponse:
    """Recognize a problem. Real image understanding is delegated to upstream when configured."""
    subject = normalize_subject(subject)
    if not file:
        return mock_recognize(problem_text, subject)
    if file.content_type not in {"image/png", "image/jpeg", "image/webp", "application/pdf"}:
        raise HTTPException(status_code=415, detail="仅支持 PNG、JPEG、WebP 图片或 PDF")
    image_bytes = await file.read(8 * 1024 * 1024 + 1)
    if not image_bytes:
        raise HTTPException(status_code=400, detail="图片文件为空")
    if len(image_bytes) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="图片不能超过 8 MB")
    signatures = {
        "image/png": b"\x89PNG\r\n\x1a\n",
        "image/jpeg": b"\xff\xd8\xff",
        "image/webp": b"RIFF____WEBP",
        "application/pdf": b"%PDF-",
    }
    expected_signature = signatures[file.content_type or "image/png"]
    signature = image_bytes[: len(expected_signature)]
    if file.content_type == "image/webp":
        signature = signature[:4] + b"____" + image_bytes[8:12]
    if signature != expected_signature:
        raise HTTPException(status_code=415, detail="图片内容与声明类型不一致")
    image_mime = file.content_type or "image/png"
    if image_mime == "application/pdf":
        image_pages = _render_pdf_pages(image_bytes)
        source_pages = [(page, "image/png") for page in image_pages]
    else:
        _verify_image(image_bytes, image_mime)
        image_pages = [image_bytes]
        source_pages = [(image_bytes, image_mime)]
    image_pages = [_prepare_vision_image(page, source_mime)[0] for page, source_mime in source_pages]
    image_mime = "image/jpeg"
    upstream_images = image_pages if len(image_pages) > 1 else image_pages[0]
    if not MINICPM_CLIENT:
        if not problem_text.strip():
            return RecognizeResponse(
                subject=subject,
                problem="",
                confidence=0.3,
                source="mock",
                no_problems=True,
                message="这张图片中没有识别到完整题目，请对准一道题重拍，或手动输入题面。",
            )
        response = mock_recognize(problem_text, subject)
        response.subject = subject
        response.annotations = [Annotation(label="题目区域", x=0.04, y=0.05, width=0.92, height=0.9)]
        response.problems = [RecognizedProblem(id="problem-1", problem=response.problem, annotations=response.annotations)]
        response.selected_problem_id = "problem-1"
        response.session_id = ORCHESTRATOR.create_recognition_session(
            response.problem, str(_user["id"]), upstream_images, image_mime, subject
        ).id
        return response
    try:
        recognized_items: list[RecognizedProblem] = []
        successful_pages: list[bytes] = []
        last_error: Exception | None = None
        fallback_after_error = False
        recognition_prompt = (
            f'先完整扫描当前图片/PDF 页，再逐题识别页面上所有完整的{subject_name(subject)}题，最多 20 题。只返回 JSON：'
            '{"problems":[{"problem":"题面","annotations":[{"label":"题目区域","x":0,"y":0,"width":1,"height":1}]}]}。'
            f"页面上有多道题时 problems 数组必须包含每一道可读题目；不要只返回最清晰、最容易或第一道{subject_name(subject)}题。"
            "每个 problem 只放一道题及选项，保留原题编号，不合并小问，不包含页眉、栏目名或“识别如下”。"
            "必须逐字转录题面和数学符号，不要计算、改写或推断结果。"
            "数学式不要使用 LaTeX 定界符或 Markdown；仅当题目属于数学或理科时保留原有公式、单位和化学式。"
            "如果当前输入不是题目或不包含完整题目，必须返回 {\"problems\":[]}。"
            "坐标相对当前图片宽高为 0 到 1 小数；无法定位时 annotations 返回空数组。不要解题。"
        )
        for page_number, page_image in enumerate(image_pages, 1):
            try:
                result = await MINICPM_CLIENT.chat(
                    problem=f"请识别第 {page_number} 页图片中的所有{subject_name(subject)}题。",
                    message=recognition_prompt,
                    history=[],
                    tts=False,
                    stage="recognition",
                    image_bytes=page_image,
                    image_mime=image_mime,
                    subject=subject,
                )
                page_items = parse_recognition_items(result["text"] or "")
                if len(page_items) == 1:
                    retry_items: list[RecognizedProblem] = []
                    try:
                        tiles = _vertical_retry_tiles(*source_pages[page_number - 1])
                        for tile_bytes, offset, source_height, tile_height in tiles:
                            tile_result = await MINICPM_CLIENT.chat(
                                problem=f"请识别当前图片分块中的所有{subject_name(subject)}题。",
                                message=(
                                    recognition_prompt
                                    + "当前输入是原题图的上半区或下半区；只识别完整题目，边界处被截断的题目不要返回。"
                                ),
                                history=[],
                                tts=False,
                                stage="recognition",
                                image_bytes=tile_bytes,
                                image_mime=image_mime,
                                subject=subject,
                            )
                            tile_items = parse_recognition_items(tile_result["text"] or "")
                            _remap_tile_annotations(tile_items, offset, source_height, tile_height)
                            retry_items.extend(tile_items)
                    except Exception as exc:
                        LOGGER.warning(
                            "MiniCPM dense-image retry failed on PDF/image page %s: %s",
                            page_number,
                            type(exc).__name__,
                        )
                    retry_items = _unique_problems(retry_items)
                    if len(retry_items) > len(page_items):
                        page_items = retry_items
                if page_items:
                    for item_index, page_item in enumerate(page_items, start=len(recognized_items) + 1):
                        page_item.id = f"problem-{item_index}"
                        recognized_items.append(page_item)
                    successful_pages.append(page_image)
            except Exception as exc:
                last_error = exc
                LOGGER.warning("MiniCPM recognition failed on PDF/image page %s: %s", page_number, type(exc).__name__)
        if not recognized_items and problem_text:
            recognized_items = parse_recognition_items(problem_text)
            fallback_after_error = last_error is not None
            if recognized_items:
                successful_pages = image_pages
        if not recognized_items:
            if last_error is not None:
                raise last_error
            return RecognizeResponse(
                subject=subject,
                problem="",
                confidence=0.3,
                source="minicpm",
                no_problems=True,
                message="这张图片中没有识别到完整题目，请对准一道题重拍，或手动输入题面。",
            )
        context_images = successful_pages[0] if len(successful_pages) == 1 else successful_pages
        text = recognized_items[0].problem
        response = mock_recognize(text, subject)
        response.source = "mock" if fallback_after_error else "minicpm"
        response.problems = recognized_items
        response.selected_problem_id = recognized_items[0].id
        response.annotations = recognized_items[0].annotations
        if fallback_after_error:
            response.degraded = True
            response.degraded_reason = f"MiniCPM-o 识题暂不可用（{type(last_error).__name__}），已回退文本识别并保留题图。"
        response.session_id = ORCHESTRATOR.create_recognition_session(
            text, str(_user["id"]), context_images, image_mime, subject
        ).id
        return response
    except Exception as exc:
        LOGGER.exception("MiniCPM image recognition failed")
        if not problem_text.strip():
            raise HTTPException(
                status_code=502,
                detail="MiniCPM-o 识题失败（上游超时或不可用）。请减少 PDF 页数、降低图片清晰度要求后重试，或手动输入题面。",
            ) from exc
        response = mock_recognize(problem_text, subject)
        response.problems = [RecognizedProblem(id="problem-1", problem=response.problem)]
        response.selected_problem_id = "problem-1"
        response.session_id = ORCHESTRATOR.create_recognition_session(
            response.problem, str(_user["id"]), upstream_images, image_mime, subject
        ).id
        response.degraded = True
        response.degraded_reason = f"MiniCPM-o 识题暂不可用（{type(exc).__name__}），已保留题图，确认后讲解将自动重试。"
        return response


@app.post("/api/lesson", response_model=LessonResponse)
async def lesson(
    request: LessonRequest,
    _user: dict[str, Any] = Depends(_current_user_required),
) -> LessonResponse:
    subject = normalize_subject(request.subject)
    session = ORCHESTRATOR.get_or_create(request.session_id, request.problem, str(_user["id"]), subject)
    if not MINICPM_CLIENT:
        response = mock_lesson(session.problem, request.message, request.stage, subject)
        response.session_id = session.id
        ORCHESTRATOR.commit(session, request.message, response.reply, request.stage)
        return response
    try:
        result = await MINICPM_CLIENT.chat(
            session.problem,
            request.message,
            session.history,
            request.tts,
            stage=request.stage,
            image_bytes=session.image_bytes,
            image_mime=session.image_mime,
            audio_base64=request.audio_base64,
            audio_sample_rate=request.audio_sample_rate,
            subject=subject,
        )
        text = result["text"] or "模型没有返回可读内容，请重试。"
        steps, parsed_answer = structured_steps(text)
        response = LessonResponse(
            subject=subject,
            session_id=session.id,
            stage=request.stage,
            reply=text,
            steps=steps or mock_lesson(session.problem, request.message, request.stage, subject).steps,
            final_answer=parsed_answer if request.stage == "explain" else None,
            next_question=next_question_from_text(text),
            confidence=0.72,
            source="minicpm",
            audio_base64=result.get("audio_base64"),
            audio_mime=result.get("audio_mime"),
        )
        ORCHESTRATOR.commit(session, request.message, text, request.stage)
        return response
    except Exception as exc:
        LOGGER.exception("MiniCPM lesson request failed")
        response = mock_lesson(session.problem, request.message, request.stage, subject)
        response.session_id = session.id
        response.reply = f"上游暂时不可用，已切换演示讲解。原因：{type(exc).__name__}"
        ORCHESTRATOR.commit(session, request.message, response.reply, request.stage)
        return response


@app.post("/api/speech", response_model=SpeechResponse)
async def speech(
    request: SpeechRequest,
    _user: dict[str, Any] = Depends(_current_user_required),
) -> SpeechResponse:
    """Generate audio for existing lesson text without changing teaching state."""
    if not MINICPM_CLIENT:
        raise HTTPException(status_code=503, detail="当前为 Mock 模式，请使用浏览器朗读。")
    subject = normalize_subject(request.subject)
    try:
        result = await MINICPM_CLIENT.chat(
            request.text,
            "请原样朗读这段内容。",
            [],
            True,
            stage="speech",
            subject=subject,
        )
    except Exception as exc:
        LOGGER.exception("MiniCPM speech request failed")
        raise HTTPException(status_code=502, detail="语音生成暂不可用，请稍后重试。") from exc
    audio_base64 = result.get("audio_base64")
    if not audio_base64:
        raise HTTPException(status_code=502, detail="模型没有返回语音数据，请稍后重试。")
    return SpeechResponse(
        audio_base64=audio_base64,
        audio_mime=result.get("audio_mime") or "audio/wav",
    )


@app.post("/api/lesson/stream")
async def lesson_stream(
    request: LessonRequest,
    _user: dict[str, Any] = Depends(_current_user_required),
) -> StreamingResponse:
    subject = normalize_subject(request.subject)
    session = ORCHESTRATOR.get_or_create(request.session_id, request.problem, str(_user["id"]), subject)

    async def event_generator():
        yield _sse({"type": "session", "session_id": session.id})
        if not MINICPM_CLIENT:
            response = mock_lesson(session.problem, request.message, request.stage, subject)
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
                stage=request.stage,
                image_bytes=session.image_bytes,
                image_mime=session.image_mime,
                audio_base64=request.audio_base64,
                audio_sample_rate=request.audio_sample_rate,
                subject=subject,
            ):
                if event.get("type") == "text_delta" and event.get("text_delta"):
                    chunks.append(event["text_delta"])
                    yield _sse({"type": "text_delta", "text_delta": event["text_delta"]})
                elif event.get("type") == "audio_delta" and event.get("audio_data"):
                    audio_parts.append(event["audio_data"])
            text = "".join(chunks) or "模型没有返回可读内容，请重试。"
            steps, parsed_answer = structured_steps(text)
            response = LessonResponse(
                subject=subject,
                session_id=session.id,
                stage=request.stage,
                reply=text,
                steps=steps or mock_lesson(session.problem, request.message, request.stage, subject).steps,
                final_answer=parsed_answer if request.stage == "explain" else None,
                next_question=next_question_from_text(text),
                confidence=0.72,
                source="minicpm",
                audio_base64=merge_audio(audio_parts) if audio_parts else None,
                audio_mime="audio/wav" if audio_parts else None,
            )
            ORCHESTRATOR.commit(session, request.message, text, request.stage)
            yield _sse({"type": "lesson", "lesson": _model_dump(response)})
            yield _sse({"type": "done"})
        except Exception as exc:
            LOGGER.exception("MiniCPM lesson stream failed")
            response = mock_lesson(session.problem, request.message, request.stage, subject)
            response.session_id = session.id
            response.reply = f"上游暂时不可用，已切换演示讲解。原因：{type(exc).__name__}"
            if response.reply:
                yield _sse({"type": "text_delta", "text_delta": response.reply})
            ORCHESTRATOR.commit(session, request.message, response.reply, request.stage)
            yield _sse({"type": "lesson", "lesson": _model_dump(response)})
            yield _sse({"type": "done"})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def _public_notebook_item(item: dict[str, Any]) -> dict[str, Any]:
    topic = item.get("topic") or classify_topic(item.get("problem"))
    return {
        "id": item.get("id"),
        "problem": item.get("problem"),
        "topic": topic,
        "topic_label": topic_label(topic),
        "helpful": bool(item.get("helpful")),
        "note": item.get("note") or "",
        "stage": item.get("stage"),
        "final_answer": item.get("final_answer") if item.get("helpful") else None,
        "reply": item.get("reply") if item.get("helpful") else None,
        "created_at": item.get("created_at"),
        "attempt_count": int(item.get("attempt_count") or 0),
        "correct_count": int(item.get("correct_count") or 0),
        "latest_attempt": item.get("latest_attempt"),
        "latest_correct": bool(item.get("latest_correct")),
        "consecutive_wrong": int(item.get("consecutive_wrong") or 0),
    }


def _retry_hint(topic: str, attempt_number: int, final_answer: str | None) -> dict[str, Any]:
    level = max(1, min(3, int(attempt_number)))
    if level == 1:
        return {
            "level": level,
            "title": "先定位知识点",
            "body": f"这题考查「{topic_label(topic)}」。先找出题目给出的条件和要求的目标，再回忆这类题的第一步。",
        }
    if level == 2:
        return {
            "level": level,
            "title": "关键步骤提示",
            "body": f"把条件代入「{topic_label(topic)}」的核心关系，先列出等式或图形关系，再逐步化简；不要急着算到底。",
        }
    return {
        "level": level,
        "title": "参考答案已展示",
        "body": f"参考答案是 {final_answer}" if final_answer else "这题暂没有保存参考答案，可回到讲解页生成完整解析后再重练。",
    }


def _retry_answer(item: dict[str, Any]) -> str:
    expected = str(item.get("final_answer") or "")
    if expected:
        return expected
    normalized_problem = normalize_problem(str(item.get("problem") or ""))
    return next(
        (
            str(question.get("final_answer") or "")
            for question in practice_bank()
            if normalize_problem(str(question.get("problem") or "")) == normalized_problem
            and question.get("final_answer")
        ),
        "",
    )


@app.post("/api/feedback")
async def feedback(
    request: FeedbackRequest,
    user: dict[str, Any] = Depends(_current_user_required),
) -> dict[str, Any]:
    item = AUTH_STORE.save_notebook_item(
        user_id=str(user["id"]),
        problem=request.problem,
        topic=classify_topic(request.problem),
        helpful=request.helpful,
        note=request.note,
        stage=request.stage,
        final_answer=request.final_answer,
        reply=request.reply,
    )
    message = "已加入错题本，可继续练同类题。" if not request.helpful else "已记录：这题掌握了。"
    return {"status": "accepted", "message": message, "item": _public_notebook_item(item)}


@app.get("/api/notebook")
async def list_notebook(
    filter: str = "all",
    topic: str | None = None,
    limit: int = 50,
    user: dict[str, Any] = Depends(_current_user_required),
) -> dict[str, Any]:
    kind = filter if filter in {"all", "wrong", "mastered"} else "all"
    items = AUTH_STORE.list_notebook_items(
        str(user["id"]),
        filter_kind=kind,
        topic=topic,
        limit=limit,
    )
    stats = AUTH_STORE.notebook_stats(str(user["id"]))
    return {"items": [_public_notebook_item(item) for item in items], "stats": stats}


@app.delete("/api/notebook/{item_id}")
async def delete_notebook_item(
    item_id: str,
    user: dict[str, Any] = Depends(_current_user_required),
) -> dict[str, bool]:
    return {"deleted": AUTH_STORE.delete_notebook_item(str(user["id"]), item_id)}


@app.get("/api/notebook/{item_id}/attempts")
async def list_notebook_attempts(
    item_id: str,
    limit: int = 50,
    offset: int = 0,
    user: dict[str, Any] = Depends(_current_user_required),
) -> dict[str, Any]:
    item = AUTH_STORE.get_notebook_item(str(user["id"]), item_id)
    if not item:
        raise HTTPException(status_code=404, detail="错题不存在")
    attempts = AUTH_STORE.list_notebook_attempts(
        str(user["id"]), item_id, limit=limit, offset=offset
    )
    total = AUTH_STORE.count_notebook_attempts(str(user["id"]), item_id)
    return {
        "item": _public_notebook_item(item),
        "attempts": attempts,
        "pagination": {"total": total, "limit": limit, "offset": offset},
    }


@app.post("/api/notebook/{item_id}/attempts")
async def submit_notebook_attempt(
    item_id: str,
    request: NotebookAttemptRequest,
    user: dict[str, Any] = Depends(_current_user_required),
) -> dict[str, Any]:
    try:
        attempt, updated = AUTH_STORE.record_notebook_attempt(
            user_id=str(user["id"]),
            item_id=item_id,
            answer=request.answer,
            evaluate_answer=lambda retry_item: answers_equivalent(
                _retry_answer(retry_item), request.answer
            ),
        )
    except NotebookConflictError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    correct = bool(attempt.get("correct"))
    attempt_number = int(attempt.get("attempt_number") or 0)
    expected_answer = _retry_answer(updated)
    reveal_answer = not correct and attempt_number >= 3 and bool(expected_answer)
    if correct:
        hint = {
            "level": 0,
            "title": "回答正确",
            "body": "答案等价判定通过，这题已标记掌握。",
        }
    else:
        hint = _retry_hint(
            str(updated.get("topic") or "general"),
            attempt_number,
            expected_answer if reveal_answer else None,
        )
    return {
        "correct": correct,
        "attempt": attempt,
        "item": _public_notebook_item(updated),
        "hint": hint,
        "final_answer": expected_answer if reveal_answer else None,
        "can_mark_mastered": reveal_answer,
    }


@app.post("/api/notebook/{item_id}/mastered")
async def mark_notebook_mastered(
    item_id: str,
    user: dict[str, Any] = Depends(_current_user_required),
) -> dict[str, Any]:
    try:
        item = AUTH_STORE.mark_notebook_mastered(
            str(user["id"]),
            item_id,
            answer_available=lambda retry_item: bool(_retry_answer(retry_item)),
        )
    except NotebookConflictError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"item": _public_notebook_item(item)}


@app.post("/api/practice/recommend")
async def practice_recommend(
    request: PracticeRecommendRequest,
    user: dict[str, Any] = Depends(_current_user_required),
) -> dict[str, Any]:
    existing = AUTH_STORE.list_notebook_item_overviews(str(user["id"]))
    preferred = [str(item.get("topic") or "") for item in existing if not item.get("helpful")]
    exclude = list(request.exclude) + [str(item.get("problem") or "") for item in existing]
    return recommend_practice(
        problem=request.problem,
        topic=request.topic,
        exclude=exclude,
        preferred_topics=preferred,
        limit=request.limit,
        subject=request.subject,
    )


@app.delete("/api/session/{session_id}")
async def delete_session(
    session_id: str,
    user: dict[str, Any] = Depends(_current_user_required),
) -> dict[str, bool]:
    return {"deleted": ORCHESTRATOR.delete(session_id, str(user["id"]))}


def _frontend_index() -> Path:
    dist_index = FRONTEND_DIST / "index.html"
    if dist_index.exists():
        return dist_index
    return STATIC_DIR / "index.html"


def _static_file(base_dir: Path, relative_path: str) -> Path | None:
    base = base_dir.resolve()
    try:
        candidate = (base_dir / relative_path).resolve()
        candidate.relative_to(base)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


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
    candidate = _static_file(FRONTEND_DIST, full_path)
    if candidate:
        return FileResponse(candidate)
    static_candidate = _static_file(STATIC_DIR, full_path)
    if static_candidate:
        return FileResponse(static_candidate)
    return FileResponse(_frontend_index())
