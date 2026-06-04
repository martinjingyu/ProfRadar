from __future__ import annotations

import os
from pathlib import Path

from .paths import PROJECT_ROOT


LOCAL_ENV_PATH = PROJECT_ROOT / ".env"
PROJECT_ENV_PATH = PROJECT_ROOT.parent / ".env"


def load_env(path: Path) -> None:
    env_path = path
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_dotenv(path: Path | None = None) -> None:
    if path is not None:
        load_env(path)
        return
    load_env(LOCAL_ENV_PATH)
    load_env(PROJECT_ENV_PATH)


def get_env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


load_dotenv()
