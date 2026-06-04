from __future__ import annotations

import json
import time
from typing import Any


class ConsoleUI:
    def __init__(self, *, enabled: bool = True, preview_chars: int = 180) -> None:
        self.enabled = enabled
        self.preview_chars = preview_chars
        self._tool_counter = 0
        self._step_started = False

    def event(self, label: str, detail: str = "") -> None:
        if not self.enabled:
            return
        ts = time.strftime("%H:%M:%S")
        suffix = f" {detail}" if detail else ""
        print(f"[{ts}] {label}{suffix}", flush=True)

    def session_start(self, session_id: str, task_id: str) -> None:
        self._box(
            "session",
            [
                ("id", session_id),
                ("task", task_id),
            ],
        )

    def model_start(self, iteration: int) -> None:
        if not self.enabled:
            return
        if self._step_started:
            print("", flush=True)
        self._step_started = True
        self._rule(f"step {iteration} | model")

    def tool_start(self, name: str, args: dict[str, Any]) -> None:
        self._tool_counter += 1
        self._box(
            f"tool {self._tool_counter} start | {name}",
            [("args", self._pretty(args, self.preview_chars * 3))],
        )

    def tool_done(self, name: str, result: str) -> None:
        ok = self._success(result)
        status = "ok" if ok else "error"
        self._box(
            f"tool {self._tool_counter} done | {name} | {status}",
            [("result", self._pretty_result(result))],
        )

    def compact(self, reason: str) -> None:
        self._box("context compact", [("reason", reason)])

    def interrupt(self) -> None:
        self._box(
            "interrupt",
            [
                ("status", "paused by user"),
                ("next", "enter a correction to continue, or /stop to save and exit"),
            ],
        )

    def final(self) -> None:
        self._box("final", [("status", "assistant response ready")])

    def saved(self, path: str) -> None:
        self._box("saved", [("session", path)])

    def self_review_start(self) -> None:
        self._rule("self-review")

    def self_review_done(self) -> None:
        self._box("self-review", [("status", "complete")])

    def _preview(self, value: Any) -> str:
        if isinstance(value, str):
            text = value
        else:
            try:
                text = json.dumps(value, ensure_ascii=False)
            except TypeError:
                text = str(value)
        text = " ".join(text.split())
        if len(text) > self.preview_chars:
            text = text[: self.preview_chars - 3] + "..."
        return text

    def _pretty(self, value: Any, limit: int) -> str:
        if isinstance(value, str):
            text = value
        else:
            try:
                text = json.dumps(value, ensure_ascii=False, indent=2)
            except TypeError:
                text = str(value)
        text = text.strip()
        if len(text) > limit:
            return text[: limit - 22] + "\n... [truncated]"
        return text

    def _pretty_result(self, result: str) -> str:
        try:
            data = json.loads(result)
        except Exception:
            return self._pretty(result, self.preview_chars * 4)
        if isinstance(data, dict):
            compact: dict[str, Any] = {}
            for key in ("success", "error", "message", "path", "url", "title", "element_count", "clicked", "direction", "returncode"):
                if key in data:
                    compact[key] = data[key]
            if "snapshot" in data:
                compact["snapshot"] = self._preview(str(data["snapshot"]))
            if "stdout" in data:
                compact["stdout"] = self._preview(str(data["stdout"]))
            if "stderr" in data and data["stderr"]:
                compact["stderr"] = self._preview(str(data["stderr"]))
            if compact:
                return self._pretty(compact, self.preview_chars * 4)
        return self._pretty(data, self.preview_chars * 4)

    def _rule(self, title: str) -> None:
        if not self.enabled:
            return
        ts = time.strftime("%H:%M:%S")
        label = f" {ts} {title} "
        width = 88
        if len(label) >= width:
            print(label.strip(), flush=True)
            return
        left = 4
        right = width - len(label) - left
        print(("=" * left) + label + ("=" * right), flush=True)

    def _box(self, title: str, rows: list[tuple[str, str]]) -> None:
        if not self.enabled:
            return
        width = 88
        top = "+" + "-" * (width - 2) + "+"
        title_line = f"| {title[: width - 5].ljust(width - 4)} |"
        print(top, flush=True)
        print(title_line, flush=True)
        print("|" + "-" * (width - 2) + "|", flush=True)
        for key, value in rows:
            key_prefix = f"{key}: "
            lines = str(value).splitlines() or [""]
            for idx, line in enumerate(lines):
                prefix = key_prefix if idx == 0 else " " * len(key_prefix)
                available = width - 4 - len(prefix)
                for wrapped in self._wrap(line, available):
                    print(f"| {prefix}{wrapped.ljust(available)} |", flush=True)
                    prefix = " " * len(key_prefix)
        print(top, flush=True)

    @staticmethod
    def _wrap(text: str, width: int) -> list[str]:
        if width <= 0:
            return [text]
        if not text:
            return [""]
        chunks: list[str] = []
        current = text
        while len(current) > width:
            split_at = current.rfind(" ", 0, width)
            if split_at <= 0:
                split_at = width
            chunks.append(current[:split_at])
            current = current[split_at:].lstrip()
        chunks.append(current)
        return chunks

    @staticmethod
    def _success(result: str) -> bool:
        try:
            data = json.loads(result)
        except Exception:
            return True
        if isinstance(data, dict) and data.get("success") is False:
            return False
        if isinstance(data, dict) and data.get("error"):
            return False
        return True
