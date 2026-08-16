from __future__ import annotations

import base64
import binascii
import io
import json
import os
import re
import struct
import wave
from typing import Any, AsyncIterator

import httpx

from .model_config import load_model_config
from .models import Step
from .subjects import normalize_subject, subject_name, SUBJECT_FOCUS


SYSTEM_PROMPT = """你是一名耐心的中文中小学全科老师。遵守以下教学约束：
1. 先确认题面，再用苏格拉底式提问引导学生，不要默认直接公布答案。
2. 提示阶段每轮只推进一个小目标：先回应学生当前想法，再给必要的最小提示，最后只提出一个具体、可直接回答的问题。
3. 学生明确要求完整解析时再给最终答案；不确定时要明确标记不确定性。
4. 输出简洁、适合学生阅读的中文，数学公式使用 LaTeX。
5. 不要输出 <think> 思考过程，直接输出给学生阅读的内容。
"""


def next_question_from_text(text: str) -> str:
    """Return the final student-facing question from a guided response."""
    questions = re.findall(r"[^。！？?\n]*[？?]", text)
    if not questions:
        return "你愿意先试着回答这个小问题吗？"
    return questions[-1].strip(" -*#\t")

def structured_steps(text: str) -> tuple[list[Step], str | None]:
    """Extract a lightweight teaching outline from the model's markdown response."""
    lines = [line.strip(" -\t") for line in text.splitlines() if line.strip()]
    steps: list[Step] = []
    for line in lines:
        match = re.match(r"(?:步骤\s*)?(\d+)[.、:)：]\s*(.+)", line)
        if match:
            steps.append(Step(title=f"第 {match.group(1)} 步", body=match.group(2), state="active"))
    answer = None
    answer_match = re.search(r"(?:最终答案|答案)\s*[：:]\s*(.+)", text)
    if answer_match:
        answer = answer_match.group(1).splitlines()[0].strip(" `。")
    return steps[:6], answer


class MiniCPMClient:
    """vLLM-Omni OpenAI-compatible client for MiniCPM-o 4.5."""

    def __init__(
        self,
        base_url: str,
        model: str | None = None,
        tls_verify: bool = True,
        api_key: str = "",
    ):
        normalized = base_url.rstrip("/")
        if normalized.endswith("/chat/completions"):
            normalized = normalized[: -len("/chat/completions")]
        elif normalized.endswith("/v1"):
            pass
        elif "/v1/" not in normalized:
            normalized += "/v1"
        self.base_url = normalized
        self.model = model or load_model_config()["model"]
        self.tls_verify = tls_verify
        self.api_key = api_key or load_model_config().get("api_key", "")

    @property
    def completions_url(self) -> str:
        return f"{self.base_url}/chat/completions"

    @property
    def ws_url(self) -> str:
        """Compatibility alias retained for callers/tests from the Gateway adapter."""
        return self.completions_url

    @staticmethod
    def _data_url(data: bytes, mime: str) -> str:
        return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"

    def _request_headers(self) -> dict[str, str]:
        headers = {"Accept": "text/event-stream"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @staticmethod
    def _float32_to_wav(audio_base64: str, sample_rate: int) -> bytes:
        """Convert browser Float32 PCM Base64 to the WAV expected by vLLM-Omni."""
        try:
            raw = base64.b64decode(audio_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("音频 Base64 格式无效") from exc
        if len(raw) % 4 != 0:
            raise ValueError("音频数据长度无效")
        sample_count = len(raw) // 4
        max_samples = min(max(sample_rate, 8000), 48000) * 60
        if sample_count > max_samples:
            raise ValueError("音频最长支持 60 秒")
        samples = struct.unpack(f"<{len(raw) // 4}f", raw[: len(raw) - len(raw) % 4])
        pcm = bytearray()
        for sample in samples:
            clipped = max(-1.0, min(1.0, sample))
            pcm.extend(struct.pack("<h", int(clipped * (32767 if clipped >= 0 else 32768))))
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(pcm)
        return output.getvalue()

    @classmethod
    def _messages(
        cls,
        problem: str,
        message: str,
        history: list[dict[str, Any]],
        stage: str,
        image_bytes: bytes | list[bytes] | None = None,
        image_mime: str = "image/png",
        audio_base64: str | None = None,
        audio_sample_rate: int = 16000,
        subject: str = "math",
    ) -> list[dict[str, Any]]:
        subject = normalize_subject(subject)
        name = subject_name(subject)
        focus = SUBJECT_FOCUS[subject]
        subject_prompt = (
            f"当前学科：{name}。围绕{focus}教学，使用该学科的规范术语和答题方法。"
            if subject != "math"
            else "当前学科：数学。数学公式使用 LaTeX，并检查计算和单位。"
        )
        messages: list[dict[str, Any]] = [{"role": "system", "content": f"{SYSTEM_PROMPT}\n{subject_prompt}"}]
        messages.extend(history[-8:])
        stage_instructions = {
            "hint": "当前请求阶段：hint。只推进一个小目标，内容控制在 3 句话以内；绝不能给出最终答案或答案数值；结尾只提出一个具体问题，让学生可以用一句话、一个式子或一个选项回答。",
            "explain": "当前请求阶段：explain。请给完整分步解析，并用一小段归纳这类题的可迁移方法，最后单独一行输出“最终答案：...”。",
            "practice": "当前请求阶段：practice。请围绕当前题目给同类练习和学习建议，不要直接泄露原题答案。",
            "recognition": "当前请求阶段：recognition。只按用户要求返回题面识别 JSON，不要解题，不要额外解释。",
            "speech": "当前请求阶段：speech。只原样朗读给定内容，不要改写、解释或补充。",
        }
        stage_instruction = stage_instructions.get(stage, stage_instructions["hint"])
        if stage == "speech":
            prompt_text = f"{stage_instruction}\n朗读内容：{problem}"
        elif audio_base64:
            prompt_text = (
                f"{stage_instruction}\n题目：{problem}\n"
                f"学生通过附带语音输入，请先理解语音中的问题或回答，并以语音内容为准。\n辅助要求：{message}"
            )
        else:
            prompt_text = f"{stage_instruction}\n题目：{problem}\n学生说：{message}"
        content: list[dict[str, Any]] = [
            {"type": "text", "text": prompt_text}
        ]
        image_items = image_bytes if isinstance(image_bytes, list) else ([image_bytes] if image_bytes else [])
        for image_item in image_items:
            content.append({"type": "image_url", "image_url": {"url": cls._data_url(image_item, image_mime)}})
        if audio_base64:
            wav = cls._float32_to_wav(audio_base64, audio_sample_rate)
            content.append({"type": "audio_url", "audio_url": {"url": cls._data_url(wav, "audio/wav")}})
        messages.append({"role": "user", "content": content} if len(content) > 1 else {"role": "user", "content": content[0]["text"]})
        return messages

    def _payload(
        self,
        problem: str,
        message: str,
        history: list[dict[str, Any]],
        tts: bool,
        image_bytes: bytes | list[bytes] | None = None,
        image_mime: str = "image/png",
        audio_base64: str | None = None,
        audio_sample_rate: int = 16000,
        stream: bool = True,
        stage: str = "hint",
        subject: str = "math",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages(problem, message, history, stage, image_bytes, image_mime, audio_base64, audio_sample_rate, subject),
            "stream": stream,
            "temperature": 0.2,
            "top_p": 0.8,
            "max_tokens": 3200 if stage == "recognition" else 512,
            "modalities": ["text", "audio"] if tts else ["text"],
        }
        payload["chat_template_kwargs"] = {
            "enable_thinking": False,
            **({"use_tts_template": True} if tts else {}),
        }
        return payload

    @staticmethod
    def _choice_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for choice in payload.get("choices") or []:
            delta = choice.get("delta") or {}
            message = choice.get("message") or {}
            text = delta.get("content") or message.get("content") or ""
            if isinstance(text, list):
                text = "".join(item.get("text", "") for item in text if isinstance(item, dict))
            audio = delta.get("audio") or message.get("audio")
            if isinstance(audio, dict):
                audio = audio.get("data")
            if not audio and payload.get("modality") == "audio":
                audio = delta.get("content") or message.get("content")
            if audio:
                events.append({"type": "audio_delta", "audio_data": audio, "audio_mime": "audio/wav"})
                continue
            if text:
                events.append({"type": "text_delta", "text_delta": text})
        return events

    @staticmethod
    def _timeout(stage: str) -> httpx.Timeout:
        default_read_timeout = 180 if stage == "recognition" else 90
        read_timeout = int(os.getenv("MINICPM_READ_TIMEOUT_SECONDS", str(default_read_timeout)))
        read_timeout = min(max(read_timeout, 10), 600)
        return httpx.Timeout(connect=10, read=read_timeout, write=30, pool=10)

    async def stream(
        self,
        problem: str,
        message: str,
        history: list[dict[str, Any]],
        tts: bool,
        image_bytes: bytes | list[bytes] | None = None,
        image_mime: str = "image/png",
        audio_base64: str | None = None,
        audio_sample_rate: int = 16000,
        stage: str = "hint",
        subject: str = "math",
    ) -> AsyncIterator[dict[str, Any]]:
        payload = self._payload(problem, message, history, tts, image_bytes, image_mime, audio_base64, audio_sample_rate, stream=True, stage=stage, subject=subject)
        timeout = self._timeout(stage)
        headers = self._request_headers()
        async with httpx.AsyncClient(verify=self.tls_verify, timeout=timeout) as client:
            try:
                async with client.stream("POST", self.completions_url, json=payload, headers=headers) as response:
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode("utf-8", "replace")[:1000]
                        raise RuntimeError(f"vLLM-Omni HTTP {response.status_code}: {detail}")
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        for normalized in yield_from_events(event):
                            yield normalized
            except httpx.HTTPError as exc:
                raise RuntimeError(f"vLLM-Omni request failed: {exc}") from exc

    async def chat(
        self,
        problem: str,
        message: str,
        history: list[dict[str, Any]],
        tts: bool,
        image_bytes: bytes | list[bytes] | None = None,
        image_mime: str = "image/png",
        audio_base64: str | None = None,
        audio_sample_rate: int = 16000,
        stage: str = "hint",
        subject: str = "math",
    ) -> dict[str, Any]:
        text_parts: list[str] = []
        audio_parts: list[str] = []
        async for event in self.stream(problem, message, history, tts, image_bytes, image_mime, audio_base64, audio_sample_rate, stage, subject):
            if event["type"] == "text_delta":
                text_parts.append(event["text_delta"])
            elif event["type"] == "audio_delta":
                audio_parts.append(event["audio_data"])
        return {
            "text": "".join(text_parts).strip(),
            "audio_base64": merge_audio(audio_parts),
            "audio_mime": "audio/wav;rate=24000" if audio_parts else None,
        }

    @staticmethod
    def image_content(image_bytes: bytes, mime: str) -> dict[str, str]:
        return {"type": "image_url", "image_url": {"url": MiniCPMClient._data_url(image_bytes, mime)}}


def yield_from_events(payload: dict[str, Any]) -> Any:
    """Yield normalized events from one OpenAI-compatible SSE JSON object."""
    for event in MiniCPMClient._choice_events(payload):
        yield event


def merge_audio(chunks: list[str]) -> str | None:
    if not chunks:
        return None
    decoded_chunks = [base64.b64decode(chunk) for chunk in chunks]
    if decoded_chunks[0].startswith(b"RIFF") and decoded_chunks[0][8:12] == b"WAVE":
        # vLLM-Omni emits WAV audio. Streaming implementations may repeat a
        # WAV header for every chunk, so retain one header and repair sizes.
        header = bytearray(decoded_chunks[0][:44])
        pcm = b"".join(chunk[44:] if chunk.startswith(b"RIFF") else chunk for chunk in decoded_chunks)
        struct.pack_into("<I", header, 4, 36 + len(pcm))
        struct.pack_into("<I", header, 40, len(pcm))
        decoded = bytes(header) + pcm
    else:
        decoded = b"".join(decoded_chunks)
    return base64.b64encode(decoded).decode("ascii")


def configured_client() -> MiniCPMClient | None:
    settings = load_model_config()
    endpoint = settings["base_url"]
    if not endpoint:
        return None
    verify = os.getenv("VLLM_OMNI_TLS_VERIFY", os.getenv("MINICPM_TLS_VERIFY", "true")).lower() not in {"0", "false", "no"}
    return MiniCPMClient(endpoint, settings["model"], verify, settings.get("api_key", ""))
