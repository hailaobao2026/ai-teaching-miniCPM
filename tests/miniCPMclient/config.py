"""MiniCPM-o-4_5 vLLM-Omni 客户端公共配置。"""

import os
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_CONFIG = json.loads(
    (PROJECT_ROOT / "config" / "minicpm.json").read_text(encoding="utf-8")
)

# vLLM-Omni OpenAI 兼容服务地址。可用 MINICPM_BASE_URL 覆盖。
BASE_URL = os.getenv(
    "MINICPM_BASE_URL", MODEL_CONFIG["base_url"]
).rstrip("/")
API_KEY = os.getenv("MINICPM_API_KEY", "EMPTY")

# 请求中的 model 字段：默认与服务端 `vllm serve <model>` 的模型参数一致。
# 若服务端启动时加了 --served-model-name <名字>，请改成那个名字。
MODEL = os.getenv(
    "MINICPM_MODEL", MODEL_CONFIG["model"]
)

# OpenAI 兼容 REST API / Realtime WebSocket 地址
REALTIME_URL = f"{BASE_URL}/realtime"

# 演示用的默认媒体（无本地文件时使用，可被命令行 --image/--audio/--video 覆盖）
DEFAULT_IMAGE_URL = (
    "https://vllm-public-assets.s3.us-west-2.amazonaws.com/vision_model_images/"
    "cherry_blossom.jpg"
)
DEFAULT_AUDIO_URL = (
    "https://vllm-public-assets.s3.us-west-2.amazonaws.com/multimodal_asset/"
    "mary_had_lamb.ogg"
)
DEFAULT_VIDEO_URL = (
    "https://huggingface.co/datasets/raushan-testing-hf/videos-test/resolve/main/"
    "sample_demo_1.mp4"
)

# 从 MiniCPM-o-Demo 克隆下来的本地示例资源（可自行替换）
SAMPLE_VIDEO = "/tmp/MiniCPM-o-Demo/assets/samples/compile.mp4"
REF_AUDIO = "/tmp/MiniCPM-o-Demo/assets/ref_audio/ref_minicpm_signature.wav"

# MiniCPM-o 官方推荐的 system prompt
SYSTEM_PROMPT = (
    "You are MiniCPM-o, a helpful multimodal assistant that can "
    "understand images, audio and video, and respond in text and speech."
)

# 输出音频采样率（MiniCPM-o 语音输出固定 24kHz）
AUDIO_OUT_SAMPLE_RATE = 24000
# Realtime 输入音频采样率（Whisper 编码器要求 16kHz PCM16 mono）
AUDIO_IN_SAMPLE_RATE = 16000
