from __future__ import annotations

from . import codex, deepseek, openai
from ..env import get_env
from ..llm import LLMClient


def from_env() -> LLMClient:
    provider = get_env("AGENT_PROVIDER") or get_env("MODEL_PROVIDER") or get_env("SCREENING_MODEL_PROVIDER", "openai")
    provider = provider.strip().lower()
    if provider == "deepseek":
        return deepseek.v4_flash
    if provider == "codex":
        return codex.gpt54
    return openai.default


__all__ = ["codex", "deepseek", "openai", "from_env"]
