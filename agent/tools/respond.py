from __future__ import annotations

from .registry import json_result, registry


def _respond_to_user(args: dict, runtime: dict) -> str:
    message = str(args.get("message") or "").strip()
    runtime["final_response"] = message
    return json_result(success=True, message="Final response captured")


registry.register(
    "respond_to_user",
    {
        "description": (
            "Finish the current turn and send a final response to the user. "
            "Use this after completing the requested work, saving files, or reaching a clear blocker."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The final user-facing answer. Mention saved report paths and any blockers.",
                }
            },
            "required": ["message"],
        },
    },
    _respond_to_user,
)
