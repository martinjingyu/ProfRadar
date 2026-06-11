from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .agent import GeneralAgent
from .env import load_dotenv
from .state import load_session
from .ui import ConsoleUI


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ProfRadar professor research agent.")
    parser.add_argument("prompt", nargs="?", help="Task for the agent (overrides request.txt)")
    parser.add_argument("--model", default=None)
    parser.add_argument("--provider", choices=["deepseek", "codex", "openai"], help="Model provider override.")
    parser.add_argument("--no-self-review", action="store_true")
    parser.add_argument("--max-iterations", type=int, default=50)
    parser.add_argument("--chat", action="store_true", help="Start an interactive multi-turn chat session.")
    parser.add_argument("--resume", help="Resume from a session id or sessions/*.json path.")
    parser.add_argument("--quiet-actions", action="store_true", help="Hide per-action model/tool trace lines.")
    parser.add_argument(
        "--update-db",
        action="store_true",
        help="Update CSRankings data before starting the agent.",
    )
    parser.add_argument(
        "--setup-browser-profile",
        nargs="?",
        const="",
        metavar="CHROME_PROFILE",
        help="Copy an existing Chrome profile into the agent shared browser profile.",
    )
    parser.add_argument(
        "--login-browser",
        action="store_true",
        help="Open Chrome with the shared agent browser profile so you can log in manually.",
    )
    args = parser.parse_args()

    load_dotenv()

    if args.setup_browser_profile is not None:
        from .browser_profile import setup_profile
        setup_profile(args.setup_browser_profile or None)
        return

    if args.login_browser:
        from .browser_profile import login_session
        login_session()
        return

    if args.update_db:
        _update_database()

    agent = GeneralAgent(
        model=args.model,
        provider=args.provider,
        max_iterations=args.max_iterations,
        self_review=not args.no_self_review,
        ui=ConsoleUI(enabled=not args.quiet_actions),
    )
    history = _load_history(args.resume) if args.resume else []

    if args.chat:
        if args.prompt:
            history = _run_once(agent, args.prompt, history)
        print(f"Interactive session: {agent.session_id}")
        print("Type /exit to quit.")
        while True:
            try:
                prompt = input("\nYou> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not prompt:
                continue
            if prompt in {"/exit", "/quit"}:
                break
            history = _run_once(agent, prompt, history)
        return

    # Determine task: explicit arg > request.txt > error
    prompt = args.prompt
    if not prompt:
        request_file = Path("request.txt")
        if request_file.exists():
            prompt = request_file.read_text(encoding="utf-8").strip()
            if prompt:
                print(f"[Auto] Running task from request.txt ({len(prompt)} chars)")

    if not prompt:
        parser.error(
            "No task provided. Pass a prompt argument, use --chat for interactive mode, "
            "or write your task to request.txt."
        )

    _run_once(agent, prompt, history)


def _update_database() -> None:
    print("[DB] Updating CSRankings data...")
    try:
        root = Path(__file__).resolve().parents[1]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        import data_manager
        data_manager.fetch_all_data(verbose=True)
        print("[DB] Update complete.")
    except Exception as exc:
        print(f"[DB] Warning: update failed: {exc}")


def _load_history(resume: str) -> list[dict]:
    path = Path(resume)
    if path.exists():
        import json
        return json.loads(path.read_text(encoding="utf-8"))
    return load_session(resume)


def _run_once(agent: GeneralAgent, prompt: str, history: list[dict]) -> list[dict]:
    result = agent.run(prompt, history=history)
    print(result["final"])
    print(f"\nSession saved: {result['session_path']}")
    return result["messages"]
