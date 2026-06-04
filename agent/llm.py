from __future__ import annotations

import base64
import json
import os
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from openai import OpenAI


DEEPSEEK_BASE_URL = "https://api.deepseek.com"
CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"


def _provider(explicit: str | None = None) -> str:
    if explicit:
        return explicit.strip().lower()
    value = os.getenv("AGENT_PROVIDER") or os.getenv("MODEL_PROVIDER")
    if value:
        return value.strip().lower()
    if os.getenv("CODEX_MODEL"):
        return "codex"
    if os.getenv("DEEPSEEK_API_KEY"):
        return "deepseek"
    return "openai"


def _deepseek_model() -> str:
    return os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")


def _openai_model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def _codex_model() -> str:
    return os.getenv("CODEX_MODEL", "gpt-5.4")


def _default_model(provider: str) -> str:
    if provider == "codex":
        return _codex_model()
    if provider == "deepseek":
        return _deepseek_model()
    return _openai_model()


def _deepseek_extra_body() -> dict[str, Any] | None:
    thinking = os.getenv("DEEPSEEK_THINKING", "disabled").strip().lower()
    if thinking in {"enabled", "disabled"}:
        return {"thinking": {"type": thinking}}
    return None


def _read_codex_access_token() -> str:
    candidates = [
        Path(os.getenv("CODEX_HOME", str(Path.home() / ".codex"))) / "auth.json",
        Path.home() / ".hermes" / "auth.json",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        tokens = None
        providers = data.get("providers")
        if isinstance(providers, dict):
            state = providers.get("openai-codex")
            if isinstance(state, dict):
                tokens = state.get("tokens")
        if tokens is None:
            tokens = data.get("tokens")
        if isinstance(tokens, dict) and tokens.get("access_token"):
            return str(tokens["access_token"])
    raise RuntimeError("No Codex access token found. Run `codex login` first.")


def _codex_headers(token: str) -> dict[str, str]:
    headers: dict[str, str] = {
        "User-Agent": "codex_cli_rs/0.0.0",
        "originator": "codex_cli_rs",
    }
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        account_id = claims.get("https://api.openai.com/auth", {}).get("chatgpt_account_id")
        if account_id:
            headers["ChatGPT-Account-ID"] = str(account_id)
    except Exception:
        pass
    return headers


def _to_responses_input(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    instructions = ""
    items: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content") or ""

        if role == "system":
            instructions = content if isinstance(content, str) else str(content)
            continue
        if role == "user":
            text = content if isinstance(content, str) else str(content)
            items.append({"role": "user", "content": [{"type": "input_text", "text": text}]})
            continue
        if role == "assistant":
            if content:
                items.append({"role": "assistant", "content": [{"type": "output_text", "text": content}]})
            for tc in msg.get("tool_calls") or []:
                if isinstance(tc, dict):
                    function = tc.get("function") or {}
                    items.append(
                        {
                            "type": "function_call",
                            "call_id": tc.get("id", ""),
                            "name": function.get("name", ""),
                            "arguments": function.get("arguments", "{}"),
                        }
                    )
            continue
        if role == "tool":
            output = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": msg.get("tool_call_id", ""),
                    "output": output,
                }
            )

    return instructions, items


def _convert_tools_for_responses(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for tool in tools:
        if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
            function = tool["function"]
            converted.append(
                {
                    "type": "function",
                    "name": function.get("name", ""),
                    "description": function.get("description", ""),
                    "parameters": function.get("parameters", {}),
                    "strict": False,
                }
            )
        else:
            converted.append(tool)
    return converted


def _attr(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _make_tool_call(call_id: str, name: str, arguments: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments or "{}"),
    )


def _chat_completion_like(content: str | None, tool_calls: list[SimpleNamespace]) -> SimpleNamespace:
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class LLMClient:
    def __init__(self, model: str | None = None, provider: str | None = None):
        self.provider = _provider(provider)
        self.model = model or _default_model(self.provider)
        self._codex_token: str | None = None
        self.client = self._build_client()

    def _build_client(self) -> OpenAI:
        if self.provider == "codex":
            self._codex_token = _read_codex_access_token()
            return OpenAI(
                api_key=self._codex_token,
                base_url=os.getenv("CODEX_BASE_URL", CODEX_BASE_URL),
                default_headers=_codex_headers(self._codex_token),
                max_retries=0,
                timeout=120.0,
            )
        if self.provider == "deepseek":
            return OpenAI(
                api_key=os.getenv("DEEPSEEK_API_KEY"),
                base_url=os.getenv("DEEPSEEK_BASE_URL", DEEPSEEK_BASE_URL),
            )
        return OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL") or None,
        )

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
        if self.provider == "codex":
            return self._codex_chat(messages, tools)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "tools": tools or None,
            "tool_choice": "auto" if tools else None,
            "temperature": float(os.getenv("AGENT_TEMPERATURE", "0.2")),
        }
        if self.provider == "deepseek":
            extra_body = _deepseek_extra_body()
            if extra_body:
                kwargs["extra_body"] = extra_body
        return self.client.chat.completions.create(**kwargs)

    def complete_text(self, prompt: str, *, temperature: float = 0.2) -> str:
        if self.provider == "codex":
            model = os.getenv("CODEX_COMPACTION_MODEL") or os.getenv("COMPACTION_MODEL") or self.model
            return self._codex_complete(prompt, model=model)

        kwargs: dict[str, Any] = {
            "model": os.getenv("COMPACTION_MODEL", self.model),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        if self.provider == "deepseek":
            extra_body = _deepseek_extra_body()
            if extra_body:
                kwargs["extra_body"] = extra_body
        response = self.client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""

    def _codex_session_kwargs(self) -> dict[str, Any]:
        session_id = uuid.uuid4().hex
        return {
            "store": False,
            "prompt_cache_key": session_id,
            "extra_headers": {"session_id": session_id, "x-client-request-id": session_id},
        }

    def _codex_is_rate_limit(self, exc: Exception) -> bool:
        status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
        return status == 429 or "rate limit" in str(exc).lower()

    def _codex_retry(self, fn):
        max_retries = int(os.getenv("CODEX_MAX_RETRIES", "8"))
        retry_sleep = float(os.getenv("CODEX_RETRY_SLEEP", "3.5"))
        for attempt in range(max_retries + 1):
            try:
                return fn()
            except Exception as exc:
                if self._codex_is_rate_limit(exc) and attempt < max_retries:
                    print(f"[Codex] 429 rate limit; retrying in {retry_sleep}s ({attempt + 1}/{max_retries})...")
                    time.sleep(retry_sleep)
                    continue
                raise

    def _codex_complete(self, prompt: str, *, model: str) -> str:
        def run_once() -> str:
            text_parts: list[str] = []
            with self.client.responses.stream(
                model=model,
                input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
                **self._codex_session_kwargs(),
            ) as stream:
                for event in stream:
                    if event.type == "response.output_text.delta" and event.delta:
                        text_parts.append(event.delta)
                final = stream.get_final_response()
            return "".join(text_parts) or getattr(final, "output_text", "") or ""

        return self._codex_retry(run_once)

    def _codex_chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
        def run_once() -> Any:
            instructions, input_items = _to_responses_input(messages)
            kwargs: dict[str, Any] = {
                "model": self.model,
                "input": input_items,
                **self._codex_session_kwargs(),
            }
            if instructions:
                kwargs["instructions"] = instructions
            if tools:
                kwargs["tools"] = _convert_tools_for_responses(tools)
                kwargs["tool_choice"] = "auto"
                kwargs["parallel_tool_calls"] = True

            text_parts: list[str] = []
            collected: list[Any] = []
            with self.client.responses.stream(**kwargs) as stream:
                for event in stream:
                    if event.type == "response.output_text.delta" and event.delta:
                        text_parts.append(event.delta)
                    elif event.type == "response.output_item.done":
                        item = getattr(event, "item", None)
                        if item is not None:
                            collected.append(item)
                final = stream.get_final_response()

            output = getattr(final, "output", None)
            if isinstance(output, list) and not output and collected:
                output = collected

            tool_calls: list[SimpleNamespace] = []
            for item in output or []:
                if _attr(item, "type") == "function_call":
                    tool_calls.append(
                        _make_tool_call(
                            _attr(item, "call_id", ""),
                            _attr(item, "name", ""),
                            _attr(item, "arguments", "{}"),
                        )
                    )

            content = "".join(text_parts) or getattr(final, "output_text", "") or None
            return _chat_completion_like(content, tool_calls)

        return self._codex_retry(run_once)
