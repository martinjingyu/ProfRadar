from __future__ import annotations

import json
from typing import Any

from .llm import LLMClient
from .text_clean import clean_text


_MAX_RESULT_CHARS = 8_000

# Injected as a user turn when approaching the iteration limit (at 80% of budget).
_WARN_REMINDER = (
    "You are approaching the iteration limit. Begin wrapping up: "
    "synthesize findings so far and prepare your final JSON response. "
    "Do not start new research fetches."
)

# Injected when the last 2 iterations remain: expensive tools are also blocked.
_FINISH_REMINDER = (
    "Final iterations: return your result NOW as a JSON object. "
    "No more web fetches or browser actions."
)

# Tools blocked in the final 2 iterations to prevent runaway fetching.
_FINISH_BLOCKED: frozenset[str] = frozenset({
    "web_fetch",
    "read_url_pdf",
    "read_pdf",
    "browser_navigate",
    "browser_snapshot",
    "browser_click",
    "browser_type",
    "browser_press_key",
    "browser_scroll",
    "browser_back",
    "google_search",
    "bing_search",
    "baidu_search",
    "reddit_search",
})


class SubAgent:
    """Lightweight single-task agent loop for parallel use.

    No UI, no session saving, no self-review. Uses the global tool registry
    but only exposes the specified allowed_tools to the LLM.

    Context management:
    - Tool results > 8000 chars are hard-truncated (subagents are ephemeral).
    - At 80% of max_iters a wrap-up reminder is injected.
    - In the last 2 iterations expensive fetch/browser tools are blocked.
    """

    def __init__(
        self,
        *,
        allowed_tools: list[str],
        model: str | None = None,
        provider: str | None = None,
        system_prompt: str = "",
    ) -> None:
        self.llm = LLMClient(model=model, provider=provider)
        self.allowed_tools = set(allowed_tools)
        self.system_prompt = system_prompt

    def run(self, task: str, max_iters: int = 12) -> str:
        from .tools.registry import registry

        all_defs = registry.definitions()
        full_tools = [d for d in all_defs if d["function"]["name"] in self.allowed_tools]
        finish_tools = [
            d for d in full_tools
            if d["function"]["name"] not in _FINISH_BLOCKED
        ]

        warn_at = max(1, int(max_iters * 0.8))   # inject light warning here
        finish_at = max(0, max_iters - 2)          # block expensive tools here

        messages: list[dict[str, Any]] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": task})

        last_content = ""
        _warned = False
        _finished_warned = False

        for iteration in range(max_iters):
            # Inject 80% warning once, as a user turn
            if iteration == warn_at and not _warned:
                messages.append({"role": "user", "content": _WARN_REMINDER})
                _warned = True

            # Switch to restricted tool set for last 2 iterations
            if iteration >= finish_at and not _finished_warned:
                messages.append({"role": "user", "content": _FINISH_REMINDER})
                _finished_warned = True

            active_tools = finish_tools if iteration >= finish_at else full_tools

            response = self.llm.chat(messages, active_tools)
            msg = response.choices[0].message
            content = msg.content or ""
            tool_calls = getattr(msg, "tool_calls", None) or []

            if not tool_calls:
                return content or last_content

            if content:
                last_content = content

            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments or "{}",
                        },
                    }
                    for tc in tool_calls
                ],
            })

            for tc in tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    if not isinstance(args, dict):
                        args = {}
                except json.JSONDecodeError:
                    args = {}

                name = tc.function.name
                if name not in self.allowed_tools:
                    result = json.dumps(
                        {"success": False, "error": f"Tool '{name}' not available in this context."},
                        ensure_ascii=False,
                    )
                elif iteration >= finish_at and name in _FINISH_BLOCKED:
                    result = json.dumps(
                        {"success": False, "error": f"Tool '{name}' blocked — return your final result now."},
                        ensure_ascii=False,
                    )
                else:
                    result = registry.dispatch(name, args, {})

                if isinstance(result, str):
                    result = clean_text(result)
                    if len(result) > _MAX_RESULT_CHARS:
                        result = (
                            result[:_MAX_RESULT_CHARS]
                            + f"\n[truncated at {_MAX_RESULT_CHARS} chars — synthesize from what you have]"
                        )

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": name,
                    "content": result,
                })

        return last_content or "SubAgent reached max iterations without a final response."
