"""场景 1：聊天推理（纯文本对话，非流式）。

用法:
    python chat_client.py --prompt "你好，介绍一下你自己"
    python chat_client.py --prompt "1+1等于几？" --base-url http://127.0.0.1:8099/v1
"""

from __future__ import annotations

import argparse
from pathlib import Path

import utils


def run_chat(base_url: str, model: str, prompt: str, out_dir: Path) -> None:
    client = utils.make_openai_client(base_url)

    messages = [
        utils.system_message(),
        utils.user_message([utils.text_part(prompt)]),
    ]

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        modalities=["text"],                 # 只输出文本，不走 TTS 流水线
        extra_body=utils.tts_extra_body(use_tts=False),
    )
    utils.save_non_stream_response(response, out_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="MiniCPM-o-4_5 聊天推理（非流式）")
    utils.add_server_args(parser)
    parser.add_argument("--prompt", "-p", default="你好，请用一句话介绍你自己。")
    args = parser.parse_args()

    print(f"服务: {utils.resolve_base_url(args)}  模型: {args.model}")
    print(f"提问: {args.prompt}\n")
    run_chat(utils.resolve_base_url(args), args.model, args.prompt, Path(args.out_dir))


if __name__ == "__main__":
    main()
