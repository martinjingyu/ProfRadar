from __future__ import annotations

from .registry import json_result, registry


def _compact_context(args: dict, runtime: dict) -> str:
    runtime["compact_requested"] = args.get("focus") or "manual compact_context tool call"
    return json_result(success=True, message="Context compaction requested")


registry.register(
    "compact_context",
    {
        "description": "Request context compaction when the conversation is getting long or noisy.",
        "parameters": {
            "type": "object",
            "properties": {"focus": {"type": "string", "description": "What the compaction should preserve most carefully."}},
            "required": [],
        },
    },
    _compact_context,
)
