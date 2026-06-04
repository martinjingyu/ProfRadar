from __future__ import annotations

import os
import re
from pathlib import Path

from .paths import workspace_root


_DESTRUCTIVE_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\bRemove-Item\b.*\s-Recurse\b",
    r"\bdel\s+/[sq]\b",
    r"\brmdir\s+/s\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+checkout\s+--\b",
    r"\bformat\b",
]


def resolve_workspace_path(path: str | None, *, default: Path | None = None) -> Path:
    root = workspace_root()
    base = default or root
    raw = Path(path).expanduser() if path else base
    if not raw.is_absolute():
        raw = root / raw
    resolved = raw.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"Path escapes workspace root {root}: {path}")
    return resolved


def check_command(command: str) -> None:
    lowered = command.strip()
    for pattern in _DESTRUCTIVE_PATTERNS:
        if re.search(pattern, lowered, re.IGNORECASE):
            raise ValueError(f"Blocked risky command pattern: {pattern}")


def build_subprocess_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    if extra:
        env.update(extra)
    return env
