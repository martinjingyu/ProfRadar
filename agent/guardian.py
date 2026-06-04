"""
Guardian (Master) process for ProfRadar agent.

Architecture: Master-Worker (Guardian-Agent)

The Guardian is a thin, stable process that:
1. Spawns the Worker (agent) as a subprocess.
2. Monitors the Worker's exit code and a signal file.
3. If the Worker exits with code 42 (self-update signal), re-spawns it.
4. Loops until the user presses Ctrl+C or the Worker exits normally (code 0).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import shutil
from pathlib import Path
from typing import Any

SIGNAL_FILE = Path(__file__).resolve().parent / ".restart_signal.json"

RESTART_EXIT_CODE = 42

MAX_RESTART_COUNT = 10


def _read_signal() -> dict[str, Any] | None:
    if not SIGNAL_FILE.exists():
        return None
    try:
        data = json.loads(SIGNAL_FILE.read_text(encoding="utf-8"))
        SIGNAL_FILE.unlink(missing_ok=True)
        return data
    except (json.JSONDecodeError, OSError):
        SIGNAL_FILE.unlink(missing_ok=True)
        return None


def _write_signal(
    changes: list[str],
    session_id: str | None = None,
    resume_path: str | None = None,
    next_prompt: str | None = None,
) -> None:
    data: dict[str, Any] = {
        "changes": changes,
        "session_id": session_id,
        "resume_path": resume_path,
        "next_prompt": next_prompt,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    SIGNAL_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_worker_args(original_args: list[str], signal: dict[str, Any] | None) -> list[str]:
    _FLAGS_WITH_VALUE = {"--model", "--resume", "--max-iterations"}

    parsed: list[tuple[str, str | None]] = []
    positionals: list[str] = []
    i = 0
    while i < len(original_args):
        a = original_args[i]
        if a in _FLAGS_WITH_VALUE and i + 1 < len(original_args):
            parsed.append((a, original_args[i + 1]))
            i += 2
        elif a.startswith("-"):
            parsed.append((a, None))
            i += 1
        else:
            positionals.append(a)
            i += 1

    if signal and signal.get("resume_path"):
        parsed = [(f, v) for f, v in parsed if f != "--resume"]
        parsed.append(("--resume", signal["resume_path"]))

    if signal and signal.get("next_prompt"):
        positionals = [signal["next_prompt"]]

    result: list[str] = []
    for flag, value in parsed:
        result.append(flag)
        if value is not None:
            result.append(value)
    result.extend(positionals)
    return result


def _print_banner(signal: dict[str, Any] | None) -> None:
    if not signal:
        return
    changes = signal.get("changes", [])
    if not changes:
        return
    print()
    print("=" * 60)
    print("  AGENT CODE UPDATED - RESTARTED")
    print("=" * 60)
    for change in changes:
        print(f"  - {change}")
    print("=" * 60)
    print()


def _clean_pycache(root: Path) -> None:
    for cache_dir in root.rglob("__pycache__"):
        try:
            shutil.rmtree(cache_dir)
        except Exception:
            pass


def run_guardian(worker_args: list[str]) -> None:
    restart_count = 0
    signal: dict[str, Any] | None = None
    project_root = Path(__file__).resolve().parent.parent
    _clean_pycache(project_root)

    while restart_count < MAX_RESTART_COUNT:
        cmd = [sys.executable, str(project_root / "run_agent.py")]
        cmd.extend(_build_worker_args(worker_args, signal))

        if restart_count > 0:
            _print_banner(signal)
            print(f"  Restart #{restart_count} — spawning new Worker...\n")
            _clean_pycache(project_root)
        else:
            print("  Starting ProfRadar agent (Guardian mode)...\n")

        process = subprocess.Popen(
            cmd,
            cwd=os.getcwd(),
            stdin=sys.stdin,
            stdout=sys.stdout,
            stderr=sys.stderr,
            env=os.environ.copy(),
        )

        try:
            process.wait()
        except KeyboardInterrupt:
            print("\n  Received Ctrl+C, shutting down...")
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            break

        exit_code = process.returncode

        if exit_code == RESTART_EXIT_CODE:
            signal = _read_signal()
            restart_count += 1
            print(f"\n  Worker requested restart (exit code {RESTART_EXIT_CODE})...")
            continue

        if exit_code == 0:
            print("\n  Worker exited normally.")
            break

        print(f"\n  Worker exited with unexpected code {exit_code}.")
        user_input = input("  Restart? [Y/n]: ").strip().lower()
        if user_input in ("", "y", "yes"):
            restart_count += 1
            continue
        break

    if restart_count >= MAX_RESTART_COUNT:
        print(f"\n  Maximum restart count ({MAX_RESTART_COUNT}) reached. Aborting.")
        sys.exit(1)


def request_restart(
    changes: list[str],
    session_id: str | None = None,
    resume_path: str | None = None,
    next_prompt: str | None = None,
) -> None:
    _write_signal(
        changes=changes,
        session_id=session_id,
        resume_path=resume_path,
        next_prompt=next_prompt,
    )
