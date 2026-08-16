"""场景 3：语音与音频模式（音频输入 -> 文本 + 语音输出）。

支持本地音频文件或 http(s) 音频 URL。默认非流式；加 --stream 走流式。

用法:
    python audio_client.py --audio /tmp/MiniCPM-o-Demo/assets/ref_audio/ref_en_dlc_1.wav
    python audio_client.py --audio https://.../mary_had_lamb.ogg \
        --prompt "这段音频说了什么？请用语音回答"
    python audio_client.py --audio ./question.wav --stream
"""

from __future__ import annotations

import argparse
from pathlib import Path

import utils
from config import DEFAULT_AUDIO_URL


def run_audio(
    base_url: str,
    model: str,
    audio_path: str,
    prompt: str,
    stream: bool,
    out_dir: Path,
) -> None:
    client = utils.make_openai_client(base_url)

    messages = [
        utils.system_message(),
        utils.user_message([
            utils.audio_part(audio_path),   # 音频输入
            utils.text_part(prompt),
        ]),
    ]

    if stream:
        stream_resp = client.chat.completions.create(
            model=model,
            messages=messages,
            modalities=["text", "audio"],
            stream=True,
            extra_body=utils.tts_extra_body(use_tts=True),
        )
        print("[文本流] ", end="", flush=True)
        utils.save_stream_response(stream_resp, out_dir)
    else:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            modalities=["text", "audio"],
            extra_body=utils.tts_extra_body(use_tts=True),
        )
        utils.save_non_stream_response(response, out_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="MiniCPM-o-4_5 语音与音频模式")
    utils.add_server_args(parser)
    parser.add_argument(
        "--audio", "-a", default=DEFAULT_AUDIO_URL,
        help="音频文件路径或 URL（默认使用官方示例音频）",
    )
    parser.add_argument("--prompt", "-p", default="这段音频的内容是什么？请用语音回答。")
    parser.add_argument("--stream", action="store_true", help="流式输出")
    args = parser.parse_args()

    print(f"服务: {utils.resolve_base_url(args)}  模型: {args.model}")
    print(f"音频: {args.audio}\n提问: {args.prompt}\n")
    run_audio(utils.resolve_base_url(args), args.model, args.audio, args.prompt, args.stream, Path(args.out_dir))


if __name__ == "__main__":
    main()
