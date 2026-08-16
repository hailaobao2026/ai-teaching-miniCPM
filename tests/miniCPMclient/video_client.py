"""场景 6：视频对话（视频文件/URL -> 文本理解，可选语音输出）。

用法:
    python video_client.py --video /tmp/MiniCPM-o-Demo/assets/samples/compile.mp4 \
        --prompt "这个视频里发生了什么？"
    python video_client.py --video https://.../sample_demo_1.mp4 --audio
"""

from __future__ import annotations

import argparse
from pathlib import Path

import utils
from config import DEFAULT_VIDEO_URL


def run_video(
    base_url: str,
    model: str,
    video_path: str,
    prompt: str,
    with_audio: bool,
    out_dir: Path,
) -> None:
    client = utils.make_openai_client(base_url)

    messages = [
        utils.system_message(),
        utils.user_message([
            utils.video_part(video_path),   # 视频输入（本地文件自动转 base64 data URL）
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
    parser = argparse.ArgumentParser(description="MiniCPM-o-4_5 视频对话")
    utils.add_server_args(parser)
    parser.add_argument(
        "--video", "-v", default=DEFAULT_VIDEO_URL,
        help="视频文件路径或 URL（默认使用官方示例视频）",
    )
    parser.add_argument("--prompt", "-p", default="这个视频里发生了什么？请描述关键内容。")
    parser.add_argument("--audio", action="store_true", help="同时请求语音输出")
    args = parser.parse_args()

    print(f"服务: {utils.resolve_base_url(args)}  模型: {args.model}")
    print(f"视频: {args.video}\n提问: {args.prompt}\n")
    run_video(utils.resolve_base_url(args), args.model, args.video, args.prompt, args.audio, Path(args.out_dir))


if __name__ == "__main__":
    main()
