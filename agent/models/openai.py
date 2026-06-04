from __future__ import annotations

from ..env import get_env
from ..llm import LLMClient


default = LLMClient(provider="openai", model=get_env("OPENAI_MODEL", "gpt-4o-mini"))
