"""场景 7：半双工实时语音对话（Realtime WebSocket，一问一答式）。

协议：OpenAI Realtime 风格 WebSocket（vLLM-Omni 的 /v1/realtime 端点）
  - 客户端：session.update -> input_audio_buffer.append(16kHz PCM16) -> commit
  - 服务端：transcription.delta / response.audio.delta(PCM16@24k) -> done

半双工：用户说完 -> 模型完整回复（文本转写 + 语音），支持多轮对话。
（若服务端以 minicpmo_4_5_duplex.yaml 部署并带 ?duplex=1，则为全双工。）

用法:
    cd /tmp/code
    python half_duplex_voice_client.py --input-wav ./single_turn.wav
    python half_duplex_voice_client.py --input-wav ./q1.wav \
        --input-wav ./q2.wav --input-wav ./q3.wav --verbose
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
from pathlib import Path

import websockets

import utils
from config import AUDIO_IN_SAMPLE_RATE, AUDIO_OUT_SAMPLE_RATE


async def send_audio_and_await_reply(
    ws,
    model: str,
    pcm16: bytes,
    chunk_bytes: int,
    out_dir: Path,
    verbose: bool,
) -> dict:
    """发送一段 16kHz PCM16 音频，等待模型回复（文本转写 + 语音）。"""
    # 1. 校验模型
    await ws.send(json.dumps({"type": "session.update", "model": model}))

    # 2. 分片发送音频（input_audio_buffer.append）
    for i in range(0, len(pcm16), chunk_bytes):
        chunk = pcm16[i : i + chunk_bytes]
        await ws.send(json.dumps({
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(chunk).decode("ascii"),
        }))

    # 3. 提交缓冲区：开始生成（半双工 = 一次提交一轮回复）
    await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
    # 4. 通知本段输入结束
    await ws.send(json.dumps({"type": "input_audio_buffer.commit", "final": True}))

    # 5. 接收回复事件
    transcript_parts: list[str] = []
    audio_pcm = bytearray()
    audio_sr = AUDIO_OUT_SAMPLE_RATE
    done_text = done_audio = False

    while not (done_text and done_audio):
        raw = await ws.recv()
        event = json.loads(raw)
        etype = event.get("type")
        if verbose:
            print(f"  <- {etype}", flush=True)

        if etype == "transcription.delta":
            delta = event.get("delta", "")
            transcript_parts.append(delta)
            print(delta, end="", flush=True)
        elif etype == "response.audio.delta":
            b64 = event.get("audio") or ""
            if b64:
                audio_pcm.extend(base64.b64decode(b64))
            sr = event.get("sample_rate_hz")
            if isinstance(sr, int) and sr > 0:
                audio_sr = sr
        elif etype == "transcription.done":
            text = event.get("text", "")
            if text and not transcript_parts:
                transcript_parts.append(text)
                print(text, end="", flush=True)
            done_text = True
        elif etype == "response.audio.done":
            done_audio = True
        elif etype == "error":
            print(f"\n[错误] {event.get('error')} ({event.get('code')})", file=sys.stderr)
            return {"transcript": "", "audio_path": None, "ok": False}
        elif etype == "session.created":
            continue
        else:
            # 其他事件（conversation.created / response.created 等）忽略
            continue

    transcript = "".join(transcript_parts)
    saved: list[Path] = []
    if transcript:
        path = out_dir / "reply_text.txt"
        path.write_text(transcript, encoding="utf-8")
        saved.append(path)
    audio_path = None
    if audio_pcm:
        audio_path = utils.write_pcm16_wav(out_dir / "reply_audio.wav", bytes(audio_pcm), audio_sr)
        saved.append(audio_path)
    return {"transcript": transcript, "audio_path": audio_path, "ok": True, "saved": saved}


async def run_half_duplex(
    base_url: str,
    model: str,
    input_wavs: list[str],
    chunk_bytes: int,
    out_dir: Path,
    verbose: bool,
) -> None:
    url = utils.realtime_url(base_url)
    async with websockets.connect(url, max_size=64 * 1024 * 1024) as ws:
        # 等待 session.created
        first = json.loads(await ws.recv())
        if first.get("type") != "session.created":
            print(f"[异常] 首个事件不是 session.created: {first}", file=sys.stderr)
            return
        print(f"[会话已建立] {first.get('id')}  模型: {model}")
        print(f"[输入音频] {len(input_wavs)} 段, 16kHz PCM16 mono\n")

        for turn, wav_path in enumerate(input_wavs, start=1):
            pcm16 = utils.load_audio_pcm16(wav_path, target_sr=AUDIO_IN_SAMPLE_RATE)
            seconds = len(pcm16) / (AUDIO_IN_SAMPLE_RATE * 2)
            print(f"--- 第 {turn} 轮 ({wav_path}, {seconds:.1f}s) ---")
            print("[回复转写] ", end="", flush=True)
            result = await send_audio_and_await_reply(ws, model, pcm16, chunk_bytes, out_dir, verbose)
            print()
            if result.get("saved"):
                for p in result["saved"]:
                    print(f"[已保存] {p}")


def main() -> None:
    parser = argparse.ArgumentParser(description="MiniCPM-o-4_5 半双工实时语音对话")
    utils.add_server_args(parser)
    parser.add_argument("--input-wav", action="append", required=True,
                        help="输入语音 WAV，可多次传入实现多轮对话")
    parser.add_argument("--chunk-bytes", type=int, default=16000,
                        help="每次 append 的 PCM16 字节数（默认 16000 = 0.5 秒）")
    parser.set_defaults(out_dir="output_realtime")
    parser.add_argument("--verbose", action="store_true", help="打印服务端事件类型")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    asyncio.run(run_half_duplex(
        utils.resolve_base_url(args), args.model, args.input_wav, args.chunk_bytes, out_dir, args.verbose,
    ))


if __name__ == "__main__":
    main()
