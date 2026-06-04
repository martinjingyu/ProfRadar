from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .llm import LLMClient
from .paths import SESSIONS_DIR
from .prompts import SELF_REVIEW_PROMPT, build_system_prompt
from .tools import registry


def trigger_self_review(
    *,
    session_id: str,
    task_id: str,
    messages: list[dict[str, Any]],
    skills_index: str,
    model: str,
    provider: str,
    background: bool = True,
) -> None:
    """Run post-turn self-review without blocking the user's response."""
    snapshot = list(messages)

    def _run() -> None:
        try:
            _run_self_review(
                session_id=session_id,
                task_id=task_id,
                messages=snapshot,
                skills_index=skills_index,
                model=model,
                provider=provider,
            )
        except Exception as exc:
            print(f"[SelfReview:{session_id}] failed (non-fatal): {exc}")

    if background:
        thread = threading.Thread(target=_run, daemon=True, name=f"self-review-{session_id}")
        thread.start()
        print(f"[SelfReview:{session_id}] started in background")
    else:
        _run()


def _run_self_review(
    *,
    session_id: str,
    task_id: str,
    messages: list[dict[str, Any]],
    skills_index: str,
    model: str,
    provider: str,
) -> None:
    allowed = {"memory", "skills_list", "skill_view", "skill_manage"}
    tools = [tool for tool in registry.definitions() if tool["function"]["name"] in allowed]
    llm = LLMClient(model=model, provider=provider)

    review_messages: list[dict[str, Any]] = [
        {"role": "system", "content": build_system_prompt(skills_index)},
        {
            "role": "user",
            "content": (
                "Conversation transcript for self-review:\n\n"
                + format_review_transcript(messages)
                + "\n\n"
                + SELF_REVIEW_PROMPT
            ),
        },
    ]

    for _ in range(6):
        response = llm.chat(review_messages, tools)
        assistant = response.choices[0].message
        tool_calls = getattr(assistant, "tool_calls", None) or []
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": assistant.content or ""}
        if tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"},
                }
                for tc in tool_calls
            ]
            review_messages.append(assistant_msg)
            for tc in tool_calls:
                if tc.function.name not in allowed:
                    result = json.dumps({"success": False, "error": "tool not allowed in self-review"})
                else:
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    result = registry.dispatch(tc.function.name, args, {"task_id": task_id, "session_id": session_id})
                review_messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "name": tc.function.name, "content": result}
                )
            continue
        review_messages.append(assistant_msg)
        break

    _save_review_session(session_id, review_messages)
    print(f"[SelfReview:{session_id}] completed")


def format_review_transcript(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for msg in messages[-36:]:
        role = msg.get("role", "")
        if role == "assistant" and msg.get("tool_calls"):
            calls = [(tc.get("function") or {}).get("name", "?") for tc in msg.get("tool_calls", [])]
            lines.append(f"[tool calls: {', '.join(calls)}]")
        elif role == "assistant":
            content = (msg.get("content") or "")[:200]
            if content:
                lines.append(content)
        elif role == "user":
            content = (msg.get("content") or "")[:200]
            if content and not content.startswith("[CONTEXT COMPACTION"):
                lines.append(f"user: {content}")
        elif role == "tool":
            name = msg.get("name", "?")
            content = (msg.get("content") or "")[:120]
            lines.append(f"  -> {name}: {content}")
    return "\n".join(lines)


def _save_review_session(session_id: str, review_messages: list[dict[str, Any]]) -> Path:
    path = SESSIONS_DIR / f"self_review_{session_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(review_messages, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path
