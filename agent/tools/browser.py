from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path
from urllib.parse import quote_plus

from .registry import json_result, registry


CLI_PATH = Path(os.getenv("AGENT_BROWSER_CLI", str(Path(__file__).parent / "cli.js")))
SNAPSHOT_MAX_CHARS = 10_000
NAVIGATE_SNAPSHOT_MAX_CHARS = 8_000

# Per-process base port/instance.  Port layout:
#   base = 9222 + (PID % 100) * 10  →  10 slots per process, 100 process slots total.
# Within a process each thread gets its own offset so parallel SubAgents never share
# a Chrome tab, refs.json state, or user-data-dir.
_PROC_PID = os.getpid()
_BROWSER_PORT_BASE = int(os.getenv("AGENT_BROWSER_PORT", str(9222 + (_PROC_PID % 100) * 10)))
_BROWSER_INSTANCE_BASE = os.getenv("AGENT_BROWSER_INSTANCE", str(_PROC_PID))

_thread_local = threading.local()
_slot_lock = threading.Lock()
_slot_counter = [0]

_active_ports: set[int] = set()
_active_ports_lock = threading.Lock()


def _mark_port_active(port: int) -> None:
    with _active_ports_lock:
        _active_ports.add(port)


def _kill_chrome_on_port(port: int) -> None:
    """Force-kill Chrome process(es) listening on the given debugging port."""
    try:
        if os.name == "nt":
            r = subprocess.run(
                [
                    "powershell", "-Command",
                    f"Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue"
                    f" | Select-Object -ExpandProperty OwningProcess",
                ],
                capture_output=True, text=True, timeout=8,
                creationflags=0x08000000,
            )
            for line in r.stdout.splitlines():
                line = line.strip()
                if line.isdigit():
                    subprocess.run(
                        ["taskkill", "/F", "/PID", line],
                        capture_output=True, timeout=5,
                        creationflags=0x08000000,
                    )
        else:
            subprocess.run(["fuser", "-k", f"{port}/tcp"], capture_output=True, timeout=5)
    except Exception:
        pass


def _atexit_cleanup() -> None:
    """Kill every Chrome instance this process launched."""
    with _active_ports_lock:
        ports = set(_active_ports)
    for port in ports:
        _kill_chrome_on_port(port)


atexit.register(_atexit_cleanup)


def _thread_slot() -> tuple[int, str, int]:
    """Return (port, instance_id, slot_index) unique to the calling thread, allocated lazily."""
    if not hasattr(_thread_local, "port"):
        with _slot_lock:
            idx = _slot_counter[0]
            _slot_counter[0] += 1
        _thread_local.port = _BROWSER_PORT_BASE + idx
        _thread_local.instance = (
            _BROWSER_INSTANCE_BASE if idx == 0
            else f"{_BROWSER_INSTANCE_BASE}_t{idx}"
        )
        _thread_local.idx = idx
    return _thread_local.port, _thread_local.instance, _thread_local.idx


def _ensure_worker_profile(instance: str) -> None:
    """Copy the run profile to a per-thread directory on first use.

    Slot 0 (main thread) uses the run profile directly via AGENT_BROWSER_PROFILE in os.environ.
    Slots 1+ copy it to a fresh per-thread directory so parallel Chrome instances don't share
    a user-data-dir, which causes crashes and lock conflicts.
    """
    if getattr(_thread_local, "profile_ready", False):
        return

    from ..browser_profile import PROFILES_DIR

    run_profile = os.environ.get("AGENT_BROWSER_PROFILE", "")
    if not run_profile:
        _thread_local.profile_ready = True
        return

    src = PROFILES_DIR / run_profile
    dst = PROFILES_DIR / instance

    if not dst.exists() and src.exists():
        def _copy_skip(s: str, d: str) -> None:
            try:
                shutil.copy2(s, d)
            except OSError:
                pass  # skip files locked by the running Chrome in slot 0

        try:
            shutil.copytree(
                src, dst,
                ignore=shutil.ignore_patterns("*.tmp", "LOG", "LOCK", "*.lock"),
                copy_function=_copy_skip,
            )
            print(f"[Browser] Copied run profile → profiles/{instance}/")
        except Exception as exc:
            print(f"[Browser] Could not copy run profile for {instance}: {exc}")

    _thread_local.profile_ready = True


def _cli_env() -> dict[str, str]:
    """Build subprocess env for the calling thread's browser slot."""
    from ..browser_profile import ensure_browser_profile
    ensure_browser_profile()
    port, instance, idx = _thread_slot()
    env = dict(os.environ)
    env["AGENT_BROWSER_PORT"] = str(port)
    env["AGENT_BROWSER_INSTANCE"] = instance
    if idx != 0:
        _ensure_worker_profile(instance)
        env["AGENT_BROWSER_PROFILE"] = instance
    return env


def _run(command: str, *args: str, timeout: int = 60) -> dict:
    cmd = ["node", str(CLI_PATH), command, *args]
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

    port, _, _ = _thread_slot()
    _mark_port_active(port)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=_cli_env(),
            **kwargs,
        )
    except FileNotFoundError:
        return {"success": False, "error": "node not found in PATH"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"timed out after {timeout}s"}

    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()

    if stdout:
        try:
            return {"success": True, **json.loads(stdout)}
        except json.JSONDecodeError:
            pass

    if proc.returncode != 0:
        return {"success": False, "error": stderr or f"exit code {proc.returncode}"}

    return {"success": True, "output": stdout}


def _run_recovering(command: str, *args: str, timeout: int = 60) -> dict:
    """Run a CDP command; on session freeze restart the browser and retry once."""
    result = _run(command, *args, timeout=timeout)
    if not result.get("success") and "CDP command timed out" in result.get("error", ""):
        print(f"[Browser] CDP timeout on '{command}', restarting browser session and retrying...")
        close_browser()
        result = _run(command, *args, timeout=timeout)
    return result


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[truncated - call browser_snapshot to see more]"


# ---------------------------------------------------------------------------
# Public browser functions
# ---------------------------------------------------------------------------

def navigate(url: str) -> dict:
    result = _run("open", url, timeout=90)
    if not result.get("success"):
        return result
    snap = snapshot(full=True)
    text = snap.get("snapshot", "")
    truncated = len(text) > NAVIGATE_SNAPSHOT_MAX_CHARS
    return {
        "success": True,
        "url": url,
        "snapshot": _truncate_text(text, NAVIGATE_SNAPSHOT_MAX_CHARS),
        "refs": snap.get("refs", {}),
        "origin": snap.get("origin", ""),
        "truncated": truncated,
    }


def snapshot(full: bool = True) -> dict:
    result = _run("snapshot", "--json", timeout=60)
    if not result.get("success"):
        return result
    text = result.get("snapshot", "")
    if not full:
        text = _truncate_text(text, SNAPSHOT_MAX_CHARS)
    return {
        "success": True,
        "snapshot": text,
        "refs": result.get("refs", {}),
        "origin": result.get("origin", ""),
    }


def click(ref: str) -> dict:
    if ref and not ref.startswith("@"):
        ref = "@" + ref
    result = _run("click", ref, timeout=60)
    if not result.get("success"):
        return result
    return {"success": True, "clicked": ref}


def type_text(text: str) -> dict:
    result = _run("keyboard", "type", text, timeout=60)
    if not result.get("success"):
        return result
    return {"success": True, "typed": len(text)}


def press_key(key: str) -> dict:
    result = _run("keyboard", "press", key, timeout=60)
    if not result.get("success"):
        return result
    return {"success": True, "pressed": key}


def scroll(direction: str = "down", pixels: int = 600) -> dict:
    result = _run("scroll", direction, str(pixels), timeout=60)
    if not result.get("success"):
        return result
    return {"success": True, "direction": direction, "pixels": pixels}


def screenshot(path: str | None = None) -> dict:
    args = [path] if path else []
    result = _run("screenshot", *args, timeout=60)
    if not result.get("success"):
        return result
    return {"success": True, "path": result.get("output", path or "")}


def back() -> dict:
    result = _run("back", timeout=60)
    if not result.get("success"):
        return result
    return {"success": True}


def close_browser() -> dict:
    port, _, _ = _thread_slot()
    _run("close", timeout=15)
    _kill_chrome_on_port(port)  # fallback if CDP close left the process running
    with _active_ports_lock:
        _active_ports.discard(port)
    return {"success": True}


def search(engine: str, query: str) -> dict:
    q = quote_plus(query)
    urls = {
        "google": f"https://www.google.com/search?q={q}",
        "bing": f"https://www.bing.com/search?q={q}",
        "baidu": f"https://www.baidu.com/s?wd={q}",
        "reddit": f"https://www.reddit.com/search/?q={q}&sort=relevance",
    }
    return navigate(urls[engine])


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def _h_navigate(args: dict, _rt: dict) -> str:
    return json_result(**navigate(args.get("url", "")))

def _h_snapshot(args: dict, _rt: dict) -> str:
    return json_result(**snapshot(full=bool(args.get("full", True))))

def _h_click(args: dict, _rt: dict) -> str:
    return json_result(**click(args.get("ref", "")))

def _h_type(args: dict, _rt: dict) -> str:
    return json_result(**type_text(args.get("text", "")))

def _h_press_key(args: dict, _rt: dict) -> str:
    return json_result(**press_key(args.get("key", "")))

def _h_scroll(args: dict, _rt: dict) -> str:
    return json_result(**scroll(args.get("direction", "down"), int(args.get("pixels", 600))))

def _h_screenshot(args: dict, _rt: dict) -> str:
    return json_result(**screenshot(args.get("path")))

def _h_back(args: dict, _rt: dict) -> str:
    return json_result(**back())

def _h_close(args: dict, _rt: dict) -> str:
    return json_result(**close_browser())

def _h_google_search(args: dict, _rt: dict) -> str:
    return json_result(**search("google", args.get("query", "")))

def _h_bing_search(args: dict, _rt: dict) -> str:
    return json_result(**search("bing", args.get("query", "")))

def _h_baidu_search(args: dict, _rt: dict) -> str:
    return json_result(**search("baidu", args.get("query", "")))

def _h_reddit_search(args: dict, _rt: dict) -> str:
    return json_result(**search("reddit", args.get("query", "")))

def _h_save_research_notes(args: dict, _rt: dict) -> str:
    return json_result(success=True)


# ---------------------------------------------------------------------------
# Tool registrations
# ---------------------------------------------------------------------------

registry.register("browser_navigate", {
    "description": "Navigate to a URL and return an accessibility snapshot. Use direct search tools for search-engine queries.",
    "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
}, _h_navigate)

registry.register("browser_snapshot", {
    "description": "Return the current page accessibility snapshot with @ref IDs. Use full=false for a compact snapshot.",
    "parameters": {"type": "object", "properties": {"full": {"type": "boolean", "default": True}}, "required": []},
}, _h_snapshot)

registry.register("browser_click", {
    "description": "Click an element by its @ref ID from the last snapshot, e.g. e5 or @e5.",
    "parameters": {"type": "object", "properties": {"ref": {"type": "string"}}, "required": ["ref"]},
}, _h_click)

registry.register("browser_type", {
    "description": "Type text into the currently focused element. Use browser_click first to focus an input.",
    "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
}, _h_type)

registry.register("browser_press_key", {
    "description": "Press a named key such as Enter, Tab, Escape, ArrowDown, or ArrowUp.",
    "parameters": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
}, _h_press_key)

registry.register("browser_scroll", {
    "description": "Scroll the page up or down.",
    "parameters": {
        "type": "object",
        "properties": {
            "direction": {"type": "string", "enum": ["up", "down"], "default": "down"},
            "pixels": {"type": "integer", "default": 600},
        },
        "required": [],
    },
}, _h_scroll)

registry.register("browser_screenshot", {
    "description": "Save a PNG screenshot of the current page and return the saved file path.",
    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": []},
}, _h_screenshot)

registry.register("browser_back", {
    "description": "Go back to the previous page in browser history.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}, _h_back)

registry.register("browser_close", {
    "description": "Close this agent's browser instance and release its port.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}, _h_close)

registry.register("google_search", {
    "description": "Search Google directly and return a browser snapshot of the result page.",
    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
}, _h_google_search)

registry.register("bing_search", {
    "description": "Search Bing directly and return a browser snapshot of the result page. Prefer this for general web search and official pages.",
    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
}, _h_bing_search)

registry.register("baidu_search", {
    "description": "Search Baidu directly and return a browser snapshot of the result page. Use for Chinese-language and mainland China sources.",
    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
}, _h_baidu_search)

registry.register("reddit_search", {
    "description": "Search Reddit directly and return a browser snapshot of the result page. Use for community discussions and first-hand accounts.",
    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
}, _h_reddit_search)

registry.register("save_research_notes", {
    "description": (
        "Save concise notes from the current browser/web/PDF result before moving on. "
        "After this tool runs, the previous large tool result is replaced in context "
        "with these notes, and all earlier fetch results are compressed — "
        "reducing token cost while preserving key findings. "
        "Call this after every professor homepage or paper visit."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "notes": {
                "type": "string",
                "description": (
                    "Key findings as concise bullets: professor name, research focus, "
                    "notable projects/papers, lab page URL if found."
                ),
            }
        },
        "required": ["notes"],
    },
}, _h_save_research_notes)
