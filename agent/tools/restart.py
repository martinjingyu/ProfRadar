from __future__ import annotations

from .registry import json_result, registry


def _request_restart(args: dict, runtime: dict) -> str:
    changes = args.get("changes")
    if not changes or not isinstance(changes, list):
        return json_result(success=False, error="changes must be a non-empty list of strings")
    next_prompt = args.get("next_prompt")
    runtime["_pending_restart"] = [str(c) for c in changes]
    if next_prompt:
        runtime["_pending_restart_prompt"] = str(next_prompt)
    return json_result(
        success=True,
        message="Restart requested. Session will be saved and the Guardian will spawn a fresh process with the updated code.",
    )


registry.register(
    "request_restart",
    {
        "description": (
            "Signal that the agent's source code has been modified and a clean restart is needed. "
            "The current session will be saved. The Guardian will spawn a fresh process loading the new code. "
            "Only call this after using write_file or patch_file to modify source files under agent/."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "changes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Human-readable descriptions of what was changed.",
                },
                "next_prompt": {
                    "type": "string",
                    "description": "Optional prompt for the restarted agent to continue the work seamlessly.",
                },
            },
            "required": ["changes"],
        },
    },
    _request_restart,
)
