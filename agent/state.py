from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .paths import SESSIONS_DIR


def new_session_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def save_session(session_id: str, messages: list[dict[str, Any]]) -> Path:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = SESSIONS_DIR / f"{session_id}.json"
    path.write_text(json.dumps(messages, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def load_session(session_id: str) -> list[dict[str, Any]]:
    path = SESSIONS_DIR / f"{session_id}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))
