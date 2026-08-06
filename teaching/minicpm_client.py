from __future__ import annotations

import base64
import io
import json
import os
import re
import struct
import wave
from typing import Any, AsyncIterator

import httpx

from .models import Step


SYSTEM_PROMPT = """你是一名耐心的中文初中数学老师。遵守以下教学约束：
1. 先确认题面，再用苏格拉底式提问引导学生，不要默认直接公布答案。
2. 分步骤解释，每一步说明依据，并检查计算是否正确。
3. 学生明确要求完整解析时再给最终答案；不确定时要明确标记不确定性。
4. 输出简洁、适合学生阅读的中文，数学公式使用 LaTeX。
"""


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

    def __init__(self, base_url: str, model: str | None = None, tls_verify: bool = True):
        normalized = base_url.rstrip("/")
        if normalized.endswith("/chat/completions"):
            normalized = normalized[: -len("/chat/completions")]
        elif normalized.endswith("/v1"):
            pass
        elif "/v1/" not in normalized:
            normalized += "/v1"
        self.base_url = normalized
        self.model = model or os.getenv("MINICPM_MODEL", "openbmb/MiniCPM-o-4_5")
        self.tls_verify = tls_verify

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

    @staticmethod
    def _float32_to_wav(audio_base64: str, sample_rate: int) -> bytes:
        """Convert browser Float32 PCM Base64 to the WAV expected by vLLM-Omni."""
        raw = base64.b64decode(audio_base64)
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
        image_bytes: bytes | None = None,
        image_mime: str = "image/png",
        audio_base64: str | None = None,
        audio_sample_rate: int = 16000,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(history[-8:])
        content: list[dict[str, Any]] = [{"type": "text", "text": f"题目：{problem}\n学生说：{message}"}]
        if image_bytes:
            content.append({"type": "image_url", "image_url": {"url": cls._data_url(image_bytes, image_mime)}})
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
        image_bytes: bytes | None = None,
        image_mime: str = "image/png",
        audio_base64: str | None = None,
        audio_sample_rate: int = 16000,
        stream: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages(problem, message, history, image_bytes, image_mime, audio_base64, audio_sample_rate),
            "stream": stream,
            "temperature": 0.2,
            "top_p": 0.8,
            "max_tokens": 512,
            "modalities": ["text", "audio"] if tts else ["text"],
        }
        if tts:
            payload["chat_template_kwargs"] = {"use_tts_template": True}
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
            if text:
                events.append({"type": "text_delta", "text_delta": text})
            audio = delta.get("audio") or message.get("audio")
            if isinstance(audio, dict):
                audio = audio.get("data")
            if audio:
                events.append({"type": "audio_delta", "audio_data": audio, "audio_mime": "audio/wav"})
        return events

    async def stream(
        self,
        problem: str,
        message: str,
        history: list[dict[str, Any]],
        tts: bool,
        image_bytes: bytes | None = None,
        image_mime: str = "image/png",
        audio_base64: str | None = None,
        audio_sample_rate: int = 16000,
    ) -> AsyncIterator[dict[str, Any]]:
        payload = self._payload(problem, message, history, tts, image_bytes, image_mime, audio_base64, audio_sample_rate, stream=True)
        timeout = httpx.Timeout(connect=10, read=90, write=30, pool=10)
        async with httpx.AsyncClient(verify=self.tls_verify, timeout=timeout) as client:
            try:
                async with client.stream("POST", self.completions_url, json=payload, headers={"Accept": "text/event-stream"}) as response:
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
        image_bytes: bytes | None = None,
        image_mime: str = "image/png",
        audio_base64: str | None = None,
        audio_sample_rate: int = 16000,
    ) -> dict[str, Any]:
        text_parts: list[str] = []
        audio_parts: list[str] = []
        async for event in self.stream(problem, message, history, tts, image_bytes, image_mime, audio_base64, audio_sample_rate):
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
    endpoint = os.getenv("VLLM_OMNI_URL", "").strip() or os.getenv("MINICPM_GATEWAY_URL", "").strip()
    if not endpoint:
        return None
    verify = os.getenv("VLLM_OMNI_TLS_VERIFY", os.getenv("MINICPM_TLS_VERIFY", "true")).lower() not in {"0", "false", "no"}
    return MiniCPMClient(endpoint, os.getenv("MINICPM_MODEL", "openbmb/MiniCPM-o-4_5"), verify)
