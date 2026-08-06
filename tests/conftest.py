import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _default_auth_env(tmp_path, monkeypatch):
    """Keep legacy teaching tests green by disabling auth requirement,
    while still using an isolated auth db for modules that touch AUTH_STORE.
    """
    # Auth-specific tests override these env vars themselves and reload modules.
    if os.getenv("MATH_COACH_AUTH_TEST_MODE") == "1":
        yield
        return
    monkeypatch.setenv("MATH_COACH_AUTH_DB", str(tmp_path / "auth-db.json"))
    monkeypatch.setenv("MATH_COACH_AUTH_REQUIRED", "false")
    monkeypatch.setenv("SEED_DEMO_ACCOUNTS", "true")
    monkeypatch.delenv("VLLM_OMNI_URL", raising=False)
    monkeypatch.delenv("MINICPM_GATEWAY_URL", raising=False)
    yield
