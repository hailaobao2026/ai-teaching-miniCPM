"""Load runtime configuration before module-level stores are initialized."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_runtime_env() -> None:
    env_file = Path(os.getenv("MATH_COACH_ENV_FILE", str(PROJECT_ROOT / ".env")))
    load_dotenv(env_file, override=False)
