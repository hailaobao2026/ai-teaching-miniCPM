"""公共工具函数：OpenAI 客户端、媒体编码、音频处理、响应打印。"""

from __future__ import annotations

import argparse
import base64
import io
import wave
import urllib.parse
from pathlib import Path

import numpy as np

import config

_MIME = {
    "image": {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
    },
    "audio": {
        ".wav": "audio/wav", ".mp3": "audio/mpeg", ".ogg": "audio/ogg",
        ".flac": "audio/flac", ".m4a": "audio/mp4", ".aac": "audio/aac",
    },
    "video": {
        ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
        ".avi": "video/x-msvideo", ".mkv": "video/x-matroska",
    },
}


def make_openai_client(base_url: str | None = None):
    """创建指向 vLLM-Omni 服务的 OpenAI 客户端。"""
    from openai import OpenAI

    return OpenAI(api_key=config.API_KEY, base_url=base_url or config.BASE_URL)


def realtime_url(base_url: str) -> str:
    """把 OpenAI 兼容 HTTP(S) 地址转换为 Realtime WebSocket 地址。"""
    parsed = urllib.parse.urlparse(base_url.rstrip("/"))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    path = parsed.path.rstrip("/") + "/realtime"
    return urllib.parse.urlunparse((scheme, parsed.netloc, path, "", parsed.query, ""))


def media_to_data_url(path_or_url: str, kind: str) -> str:
    """本地媒体文件转 base64 data URL；http(s)/data URL 原样返回。"""
    if path_or_url.startswith(("http://", "https://", "data:")):
        return path_or_url
    path = Path(path_or_url)
    if not path.is_file():
        raise FileNotFoundError(f"媒体文件不存在: {path}")
    mime = _MIME[kind].get(path.suffix.lower())
    if mime is None:
        mime = _MIME[kind].get("." + kind, f"{kind}/octet-stream")
        if kind == "image":
            mime = "image/jpeg"
        elif kind == "audio":
            mime = "audio/wav"
        else:
            mime = "video/mp4"
    b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


# ---------------------------------------------------------------------------
# OpenAI 消息构造
# ---------------------------------------------------------------------------

def text_part(text: str) -> dict:
    return {"type": "text", "text": text}


def image_part(path_or_url: str) -> dict:
    return {"type": "image_url", "image_url": {"url": media_to_data_url(path_or_url, "image")}}


def audio_part(path_or_url: str) -> dict:
    return {"type": "audio_url", "audio_url": {"url": media_to_data_url(path_or_url, "audio")}}


def video_part(path_or_url: str) -> dict:
    return {"type": "video_url", "video_url": {"url": media_to_data_url(path_or_url, "video")}}


def system_message() -> dict:
    return {"role": "system", "content": [text_part(config.SYSTEM_PROMPT)]}


def user_message(content: list[dict]) -> dict:
    return {"role": "user", "content": content}


def tts_extra_body(use_tts: bool) -> dict:
    """启用/关闭语音输出的 chat_template_kwargs。"""
    return {"chat_template_kwargs": {"use_tts_template": use_tts}}


# ---------------------------------------------------------------------------
# 音频处理
# ---------------------------------------------------------------------------

def load_audio_pcm16(path_or_url: str, target_sr: int = 16000) -> bytes:
    """读取音频（支持 wav/ogg/mp3/flac 等），重采样为 target_sr mono PCM16。"""
    import soundfile as sf

    if path_or_url.startswith(("http://", "https://")):
        import urllib.request

        with urllib.request.urlopen(path_or_url) as resp:
            data = resp.read()
        audio, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=False)
    else:
        audio, sr = sf.read(str(path_or_url), dtype="float32", always_2d=False)

    if audio.ndim > 1:  # 多声道 -> 取平均
        audio = audio.mean(axis=1)
    audio = np.asarray(audio, dtype=np.float32)

    if sr != target_sr:  # 线性插值重采样
        scale = target_sr / float(sr)
        n_out = max(1, int(round(len(audio) * scale)))
        x_old = np.arange(len(audio), dtype=np.float64)
        x_new = np.arange(n_out, dtype=np.float64) / scale
        audio = np.interp(x_new, x_old, audio.astype(np.float64)).astype(np.float32)

    audio = np.clip(audio, -1.0, 1.0)
    pcm16 = (audio * 32767.0).astype(np.int16)
    return pcm16.tobytes()


def write_pcm16_wav(path, pcm16_bytes: bytes, sample_rate: int) -> Path:
    """把 PCM16 裸数据写成 WAV 文件。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16_bytes)
    return path


def save_base64_wav(b64_data: str, path) -> Path:
    """把 base64 编码的 WAV 保存到文件。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(b64_data))
    return path


def merge_wav_chunks(chunk_paths: list[Path], out_path, sample_rate: int = 24000) -> Path:
    """把多个（单声道 PCM16）WAV 分片拼接成单个 WAV。"""
    frames = bytearray()
    for chunk in chunk_paths:
        with wave.open(str(chunk), "rb") as wf:
            if wf.getnchannels() != 1:
                raise ValueError(f"{chunk} 不是单声道 WAV")
            frames.extend(wf.readframes(wf.getnframes()))
    return write_pcm16_wav(out_path, bytes(frames), sample_rate)


# ---------------------------------------------------------------------------
# 响应打印与保存
# ---------------------------------------------------------------------------

def save_non_stream_response(response, out_dir: Path) -> list[Path]:
    """打印非流式响应；若有语音输出则保存 WAV。返回保存的文件列表。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for idx, choice in enumerate(response.choices):
        if choice.message.audio is not None:
            audio = choice.message.audio
            transcript = getattr(audio, "transcript", None) or ""
            if transcript:
                print(f"\n[语音转写] {transcript}")
            path = save_base64_wav(audio.data, out_dir / f"audio_{idx}.wav")
            saved.append(path)
            print(f"[语音已保存] {path}")
        elif choice.message.content:
            print(f"[回复] {choice.message.content}")
    return saved


def save_stream_response(stream, out_dir: Path) -> tuple[str, list[Path]]:
    """消费流式响应：打印文本增量，保存语音分片并合并。返回 (全文, 文件列表)。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    text_parts: list[str] = []
    audio_chunks: list[Path] = []
    saved: list[Path] = []
    for chunk in stream:
        modality = getattr(chunk, "modality", None)
        for choice in chunk.choices:
            delta = getattr(choice, "delta", None)
            if delta is None:
                continue
            content = getattr(delta, "content", None) or ""
            if not content:
                continue
            if modality == "audio":
                path = save_base64_wav(content, out_dir / f"audio_chunk_{len(audio_chunks):04d}.wav")
                audio_chunks.append(path)
                print(f"[语音分片] {path}")
            elif modality == "text":
                print(content, end="", flush=True)
                text_parts.append(content)
    full_text = "".join(text_parts)
    if text_parts:
        print()
    if audio_chunks:
        merged = merge_wav_chunks(audio_chunks, out_dir / "audio_stream.wav")
        saved.append(merged)
        print(f"[语音已合并] {merged}")
    return full_text, saved


# ---------------------------------------------------------------------------
# 公共命令行参数
# ---------------------------------------------------------------------------

def add_server_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--base-url", default=config.BASE_URL,
        help="OpenAI 兼容服务地址（默认取 config.BASE_URL）",
    )
    parser.add_argument(
        "--host", default=None,
        help="本地 vLLM-Omni 服务地址；设置后优先于 --base-url",
    )
    parser.add_argument(
        "--port", type=int, default=None,
        help="本地 vLLM-Omni 服务端口；仅设置 --host 时生效",
    )
    parser.add_argument(
        "--model", default=config.MODEL,
        help="模型名，需与服务端 served model 一致（默认取 config.MODEL）",
    )
    parser.add_argument("--out-dir", default="output", help="输出文件目录（默认 output/）")


def resolve_base_url(args: argparse.Namespace) -> str:
    """解析最终服务地址，并兼容旧的 --host/--port 参数。"""
    if args.host is not None:
        return f"http://{args.host}:{args.port or 8099}/v1"
    return args.base_url.rstrip("/")
