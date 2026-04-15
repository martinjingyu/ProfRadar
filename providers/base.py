"""
Minimal LLM provider interface — just text generation, no tool use.
"""

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Generate a text response given a system prompt and a user message."""

    @abstractmethod
    def generate(self, system: str, prompt: str, max_tokens: int = 1024) -> str: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...
