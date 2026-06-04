from __future__ import annotations

from pathlib import Path

from ..paths import MEMORIES_DIR
from .registry import json_result, registry

DELIMITER = "\n§\n"


def _memory_path(target: str) -> Path:
    MEMORIES_DIR.mkdir(parents=True, exist_ok=True)
    return MEMORIES_DIR / ("USER.md" if target == "user" else "MEMORY.md")


def _read_entries(target: str) -> list[str]:
    path = _memory_path(target)
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return []
    return [entry.strip() for entry in text.split(DELIMITER) if entry.strip()]


def _write_entries(target: str, entries: list[str]) -> None:
    _memory_path(target).write_text(DELIMITER.join(entries).strip() + ("\n" if entries else ""), encoding="utf-8")


def memory_snapshot() -> str:
    parts: list[str] = []
    for target, title in (("user", "USER PROFILE"), ("memory", "AGENT MEMORY")):
        entries = _read_entries(target)
        if entries:
            parts.append(f"## {title}\n" + "\n".join(f"- {entry}" for entry in entries))
    return "\n\n".join(parts)


def _memory(args: dict, runtime: dict) -> str:
    action = str(args.get("action") or "read")
    target = str(args.get("target") or "memory")
    if target not in {"memory", "user"}:
        return json_result(success=False, error="target must be memory or user")
    entries = _read_entries(target)

    if action == "read":
        return json_result(success=True, target=target, entries=entries)
    if action == "add":
        content = str(args.get("content") or "").strip()
        if not content:
            return json_result(success=False, error="content is required")
        if content not in entries:
            entries.append(content)
            _write_entries(target, entries)
        return json_result(success=True, message="Entry added", target=target)
    if action == "replace":
        old_text = str(args.get("old_text") or "")
        content = str(args.get("content") or "").strip()
        matches = [i for i, entry in enumerate(entries) if old_text and old_text in entry]
        if len(matches) != 1:
            return json_result(success=False, error=f"Expected one match, found {len(matches)}")
        entries[matches[0]] = content
        _write_entries(target, entries)
        return json_result(success=True, message="Entry replaced", target=target)
    if action == "remove":
        old_text = str(args.get("old_text") or "")
        new_entries = [entry for entry in entries if old_text not in entry]
        removed = len(entries) - len(new_entries)
        _write_entries(target, new_entries)
        return json_result(success=True, message="Entries removed", removed=removed, target=target)
    return json_result(success=False, error="action must be read, add, replace, or remove")


registry.register(
    "memory",
    {
        "description": "Read or update persistent memory. Use user for user preferences and memory for durable agent/project facts.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["read", "add", "replace", "remove"]},
                "target": {"type": "string", "enum": ["memory", "user"], "default": "memory"},
                "content": {"type": "string"},
                "old_text": {"type": "string"},
            },
            "required": ["action"],
        },
    },
    _memory,
)
