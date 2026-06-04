from __future__ import annotations

from ..llm import LLMClient


v4_flash = LLMClient(provider="deepseek", model="deepseek-v4-flash")
v4_pro = LLMClient(provider="deepseek", model="DeepSeek-V4-Pro")
