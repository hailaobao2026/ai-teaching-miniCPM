"""场景 5：多图对话（多张图片对比/联合理解，可选语音输出）。

用法:
    python multi_image_client.py --image ./a.jpg --image ./b.jpg \
        --prompt "这两张图片有什么异同？"
    python multi_image_client.py -i img1.png -i img2.png -i img3.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

import utils


def run_multi_image(
    base_url: str,
    model: str,
    image_paths: list[str],
    prompt: str,
    with_audio: bool,
    out_dir: Path,
) -> None:
    client = utils.make_openai_client(base_url)

    content = [utils.image_part(p) for p in image_paths]  # 多张图片输入
    content.append(utils.text_part(prompt))

    messages = [utils.system_message(), utils.user_message(content)]

    modalities = ["text", "audio"] if with_audio else ["text"]

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        modalities=modalities,
        extra_body=utils.tts_extra_body(use_tts=with_audio),
    )
    utils.save_non_stream_response(response, out_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="MiniCPM-o-4_5 多图对话")
    utils.add_server_args(parser)
    parser.add_argument(
        "--image", "-i", action="append", required=True,
        help="图片路径或 URL，可多次传入（至少 2 张）",
    )
    parser.add_argument("--prompt", "-p", default="请比较这些图片的内容，并说明它们之间的异同。")
    parser.add_argument("--audio", action="store_true", help="同时请求语音输出")
    args = parser.parse_args()

    if len(args.image) < 2:
        parser.error("多图对话至少需要传入 2 张图片（--image 可重复使用）")

    print(f"服务: {utils.resolve_base_url(args)}  模型: {args.model}")
    print(f"图片数量: {len(args.image)}  提问: {args.prompt}\n")
    run_multi_image(utils.resolve_base_url(args), args.model, args.image, args.prompt, args.audio, Path(args.out_dir))


if __name__ == "__main__":
    main()
