"""场景 2：流式推理（文本逐字流式输出，可选语音分片流式输出）。

默认只输出文本；加 --audio 同时请求语音输出（流式返回 24kHz WAV 分片）。

用法:
    python streaming_client.py --prompt "写一首关于夏天的五言绝句"
    python streaming_client.py --prompt "请用语音说：你好，世界" --audio
"""

from __future__ import annotations

import argparse
from pathlib import Path

import utils


def run_streaming(
    base_url: str,
    model: str,
    prompt: str,
    with_audio: bool,
    out_dir: Path,
) -> None:
    client = utils.make_openai_client(base_url)

    messages = [
        utils.system_message(),
        utils.user_message([utils.text_part(prompt)]),
    ]

    modalities = ["text", "audio"] if with_audio else ["text"]

    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        modalities=modalities,
        stream=True,                                   # 开启流式
        extra_body=utils.tts_extra_body(use_tts=with_audio),
    )

    print("[文本流] ", end="", flush=True)
    utils.save_stream_response(stream, out_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="MiniCPM-o-4_5 流式推理")
    utils.add_server_args(parser)
    parser.add_argument("--prompt", "-p", default="请用一句话介绍 vLLM-Omni。")
    parser.add_argument("--audio", action="store_true", help="同时请求语音输出")
    args = parser.parse_args()

    print(f"服务: {utils.resolve_base_url(args)}  模型: {args.model}")
    print(f"提问: {args.prompt}  语音输出: {'是' if args.audio else '否'}\n")
    run_streaming(utils.resolve_base_url(args), args.model, args.prompt, args.audio, Path(args.out_dir))


if __name__ == "__main__":
    main()
