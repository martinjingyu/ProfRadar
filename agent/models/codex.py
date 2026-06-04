from __future__ import annotations

from ..llm import LLMClient


gpt55 = LLMClient(provider="codex", model="gpt-5.5")
gpt54 = LLMClient(provider="codex", model="gpt-5.4")
gpt54_mini = LLMClient(provider="codex", model="gpt-5.4-mini")
