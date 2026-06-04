from __future__ import annotations

from .registry import registry


def load_builtin_tools() -> None:
    from . import compact, fetch, files, memory, professors, respond, restart, skills, terminal  # noqa: F401


__all__ = ["registry", "load_builtin_tools"]
