from __future__ import annotations

from .registry import registry


def load_builtin_tools() -> None:
    from . import browser, compact, fetch, files, memory, parallel, professors, respond, skills, terminal  # noqa: F401


__all__ = ["registry", "load_builtin_tools"]
