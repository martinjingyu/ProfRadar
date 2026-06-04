from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable


Handler = Callable[[dict[str, Any], dict[str, Any]], str]


@dataclass
class Tool:
    name: str
    schema: dict[str, Any]
    handler: Handler


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, name: str, schema: dict[str, Any], handler: Handler) -> None:
        self._tools[name] = Tool(name=name, schema={**schema, "name": name}, handler=handler)

    def definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": tool.schema}
            for tool in self._tools.values()
        ]

    def dispatch(self, name: str, args: dict[str, Any], runtime: dict[str, Any]) -> str:
        tool = self._tools.get(name)
        if not tool:
            return json.dumps({"success": False, "error": f"Unknown tool: {name}"}, ensure_ascii=False)
        try:
            return tool.handler(args, runtime)
        except Exception as exc:
            return json.dumps(
                {"success": False, "error": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
            )

    @property
    def names(self) -> set[str]:
        return set(self._tools)


registry = ToolRegistry()


def json_result(**kwargs: Any) -> str:
    return json.dumps(kwargs, ensure_ascii=False)
