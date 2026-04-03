from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def load_settings() -> dict[str, str]:
    settings: dict[str, str] = {}
    env_path = Path.cwd() / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            settings[key.strip()] = value.strip().strip("\"'")

    token = os.getenv("COURTLISTENER_API_TOKEN", settings.get("COURTLISTENER_API_TOKEN", "")).strip()
    if token:
        settings["COURTLISTENER_API_TOKEN"] = token
    return settings


def get_courtlistener_token() -> str:
    return load_settings().get("COURTLISTENER_API_TOKEN", "")
