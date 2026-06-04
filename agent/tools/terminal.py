from __future__ import annotations

import subprocess

from ..safety import build_subprocess_env, check_command, resolve_workspace_path
from .registry import json_result, registry


def _terminal(args: dict, runtime: dict) -> str:
    command = str(args.get("command") or "")
    if not command:
        return json_result(success=False, error="command is required")
    check_command(command)
    workdir = resolve_workspace_path(args.get("workdir") or ".")
    timeout = int(args.get("timeout") or 60)
    proc = subprocess.run(
        command,
        cwd=str(workdir),
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding='utf-8',
        errors='replace',
        env=build_subprocess_env(),
    )
    stdout = proc.stdout[-20000:]
    stderr = proc.stderr[-8000:]
    return json_result(
        success=proc.returncode == 0,
        returncode=proc.returncode,
        stdout=stdout,
        stderr=stderr,
    )


registry.register(
    "terminal",
    {
        "description": "Run a non-destructive shell command inside the workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "workdir": {"type": "string", "default": "."},
                "timeout": {"type": "integer", "default": 60},
            },
            "required": ["command"],
        },
    },
    _terminal,
)
