"""Load MiniCPM runtime settings from the project-level model config file."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from teaching.runtime_env import load_runtime_env


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "minicpm.json"

load_runtime_env()


def _read_config_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"无法读取 MiniCPM 配置文件 {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"MiniCPM 配置文件必须是 JSON 对象: {path}")
    return payload


def load_model_config() -> dict[str, str]:
    """Read config/minicpm.json; explicit environment variables still override it."""
    path = Path(os.getenv("MINICPM_CONFIG_FILE", str(DEFAULT_CONFIG_PATH)))
    payload = _read_config_file(path)

    primary_url = os.getenv("VLLM_OMNI_URL")
    legacy_url = os.getenv("MINICPM_GATEWAY_URL")
    if primary_url is not None:
        base_url = primary_url.strip()
    elif legacy_url is not None and legacy_url.strip():
        base_url = legacy_url.strip()
    else:
        base_url = str(payload.get("base_url", "")).strip()

    configured_model = os.getenv("MINICPM_MODEL")
    model = configured_model.strip() if configured_model else str(payload.get("model", "")).strip()
    configured_api_key = os.getenv("MINICPM_API_KEY", "").strip()
    if not configured_api_key:
        api_key_env = str(payload.get("api_key_env", "")).strip()
        configured_api_key = os.getenv(api_key_env, "").strip() if api_key_env else ""
    api_key = configured_api_key or str(payload.get("api_key", "")).strip()
    if not model:
        raise RuntimeError(f"MiniCPM 配置文件缺少 model 字段: {path}")
    if len(model) > 256:
        raise RuntimeError(f"MiniCPM 模型名过长，最大 256 字符: {path}")
    if base_url:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"}:
            raise RuntimeError(f"MiniCPM base_url 仅支持 http/https: {base_url}")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise RuntimeError("MiniCPM base_url 不应包含凭据、query 或 fragment")
    return {"base_url": base_url, "model": model, "api_key": api_key}
