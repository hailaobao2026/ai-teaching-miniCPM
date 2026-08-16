"""场景 4：单图对话（一张图片 -> 文本描述，可选语音输出）。

用法:
    python single_image_client.py --image ./cat.png --prompt "描述这张图片的内容"
    python single_image_client.py --image https://.../cherry_blossom.jpg --audio
"""

from __future__ import annotations

import argparse
from pathlib import Path

import utils
from config import DEFAULT_IMAGE_URL


def run_single_image(
    base_url: str,
    model: str,
    image_path: str,
    prompt: str,
    with_audio: bool,
    out_dir: Path,
) -> None:
    client = utils.make_openai_client(base_url)

    messages = [
        utils.system_message(),
        utils.user_message([
            utils.image_part(image_path),   # 单张图片输入
            utils.text_part(prompt),
        ]),
    ]

    modalities = ["text", "audio"] if with_audio else ["text"]

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        modalities=modalities,
        extra_body=utils.tts_extra_body(use_tts=with_audio),
    )
    utils.save_non_stream_response(response, out_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="MiniCPM-o-4_5 单图对话")
    utils.add_server_args(parser)
    parser.add_argument(
        "--image", "-i", default=DEFAULT_IMAGE_URL,
        help="图片路径或 URL（默认使用官方示例图片）",
    )
    parser.add_argument("--prompt", "-p", default="这张图片里有什么？请详细描述。")
    parser.add_argument("--audio", action="store_true", help="同时请求语音输出")
    args = parser.parse_args()

    print(f"服务: {utils.resolve_base_url(args)}  模型: {args.model}")
    print(f"图片: {args.image}\n提问: {args.prompt}\n")
    run_single_image(utils.resolve_base_url(args), args.model, args.image, args.prompt, args.audio, Path(args.out_dir))


if __name__ == "__main__":
    main()
