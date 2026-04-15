"""
Professor Cold-Email Research Agent
====================================
Usage:
    python main.py                            # default provider from .env
    python main.py --provider openai --model gpt-4o-mini --limit 50
    python main.py --provider azure --limit 50
    python main.py --provider gemini --model gemini-2.0-flash
    python main.py --update                   # force-refresh CSRankings data
    python main.py --reset                    # clear saved school/interests
"""

import argparse
import asyncio
import json
import os
import random
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

CONFIG_FILE = Path(__file__).parent / ".user_config.json"


# -- Persistent config --------------------------------------------------------

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {}


def save_config(cfg: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))


# -- Provider factory ---------------------------------------------------------

def build_provider(name: str, model: str | None):
    name = name.lower()
    if name == "anthropic":
        from providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider(model=model)
    if name == "openai":
        from providers.openai_provider import OpenAIProvider
        return OpenAIProvider(model=model)
    if name == "azure":
        from providers.azure_openai_provider import AzureOpenAIProvider
        return AzureOpenAIProvider(deployment=model)
    if name == "gemini":
        from providers.gemini_provider import GeminiProvider
        return GeminiProvider(model=model)
    print(f"Unknown provider: {name}. Available: anthropic | openai | azure | gemini")
    sys.exit(1)


# -- Data bootstrap -----------------------------------------------------------

def ensure_data(force_update: bool = False) -> None:
    import data_manager as dm

    if force_update or not dm.data_exists():
        reason = "forced update" if force_update else "first run"
        print(f"\nDownloading CSRankings data ({reason})...\n")
        dm.fetch_all_data(verbose=True)
        print()
    else:
        last = dm.last_updated() or "unknown"
        ans = input(f"\nLocal data exists (updated {last}). Re-download? [y/N] ").strip().lower()
        if ans == "y":
            print()
            dm.fetch_all_data(verbose=True)
            print()


# -- School selection (with memory) -------------------------------------------

def get_school(cfg: dict) -> tuple[str, dict]:
    saved = cfg.get("school")
    if saved:
        ans = input(f"\nLast school: {saved}\n  Press Enter to keep, or 'c' to change: ").strip().lower()
        if ans != "c":
            return saved, cfg

    from school_selector import select_school
    school = select_school()
    cfg["school"] = school
    save_config(cfg)
    return school, cfg


# -- Interests input (with memory) --------------------------------------------

def get_interests(cfg: dict) -> tuple[str, dict]:
    saved_interests = cfg.get("interests", "")
    saved_extra = cfg.get("extra", "")

    if saved_interests:
        print(f"\nResearch interests: {saved_interests}")
        if saved_extra:
            print(f"Additional notes:   {saved_extra}")
        ans = input("  Press Enter to keep, or 'c' to re-enter: ").strip().lower()
        if ans != "c":
            profile = f"Research interests: {saved_interests}"
            if saved_extra:
                profile += f"\nAdditional requirements: {saved_extra}"
            return profile, cfg

    print("\n" + "-" * 62)
    interests = input(
        "Research interests\n"
        "  (e.g. NLP, LLM alignment, code generation, computer vision)\n"
        "  > "
    ).strip()
    extra = input(
        "\nAdditional requirements (optional, press Enter to skip)\n"
        "  (e.g. prefers small lab, open-source focus, strong theory background)\n"
        "  > "
    ).strip()

    cfg["interests"] = interests
    cfg["extra"] = extra
    save_config(cfg)

    profile = f"Research interests: {interests}"
    if extra:
        profile += f"\nAdditional requirements: {extra}"
    return profile, cfg


# -- Report saving ------------------------------------------------------------

def save_report(school: str, report: str) -> Path:
    out_dir = Path("output") / school.replace(" ", "_").replace("/", "-")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"match_report_{date.today().isoformat()}.md"
    path.write_text(report, encoding="utf-8")
    return path


# -- Professor sampling -------------------------------------------------------

def sample_professors(professors: list[dict], limit: int) -> list[dict]:
    """Prefer professors with known CSRankings research areas, fill rest randomly."""
    if limit <= 0 or len(professors) <= limit:
        return professors
    with_areas = [p for p in professors if p.get("areas")]
    without_areas = [p for p in professors if not p.get("areas")]
    if len(with_areas) >= limit:
        return random.sample(with_areas, limit)
    extra = random.sample(without_areas, min(limit - len(with_areas), len(without_areas)))
    return with_areas + extra


# -- Main ---------------------------------------------------------------------

async def async_main(args):
    cfg = load_config()

    # 1. Data
    ensure_data(force_update=args.update)

    # 2. School (remembered)
    school, cfg = get_school(cfg)

    # 3. Professor list
    import data_manager as dm
    professors = dm.get_professors(school)
    if not professors:
        print(f"\nNo professors found for '{school}'.")
        print("The school name must match the affiliation field in CSRankings exactly.")
        sys.exit(1)

    total_found = len(professors)
    if args.limit and args.limit < total_found:
        professors = sample_professors(professors, args.limit)
        print(f"\nFound {total_found} professors at {school} — processing {len(professors)}")
    else:
        print(f"\nFound {total_found} professors at {school}")

    # 4. Interests (remembered)
    user_profile, cfg = get_interests(cfg)

    # 5. Provider
    provider = build_provider(args.provider, args.model)
    print(f"\nModel: {provider.model_name}")

    # 6. Parallel pipeline
    from professor_pipeline import run_pipeline
    summaries = await run_pipeline(professors, school, provider)

    if not summaries:
        print("\nNo professor homepages could be accessed. Cannot generate match report.")
        sys.exit(1)

    # 7. Matching
    from matcher import match_professors
    report = match_professors(summaries, user_profile, provider)

    # 8. Display & save
    print("\n" + "=" * 62)
    print("  Recommendations")
    print("=" * 62)
    print(report)

    report_path = save_report(school, report)
    print(f"\nReport saved to: {report_path}")


def main():
    parser = argparse.ArgumentParser(description="Professor Cold-Email Research Agent")
    parser.add_argument(
        "--provider",
        default=os.environ.get("DEFAULT_PROVIDER", "openai"),
        choices=["anthropic", "openai", "azure", "gemini"],
    )
    parser.add_argument("--model", default=None, help="Model name or Azure deployment name")
    parser.add_argument("--limit", type=int, default=None, metavar="N",
                        help="Process at most N professors")
    parser.add_argument("--update", action="store_true",
                        help="Force re-download of CSRankings data")
    parser.add_argument("--reset", action="store_true",
                        help="Clear saved school and interests settings")
    args = parser.parse_args()

    if args.reset:
        CONFIG_FILE.unlink(missing_ok=True)
        print("Saved config cleared. School and interests will be asked on next run.")
        sys.exit(0)

    print("=" * 62)
    print("  Professor Cold-Email Research Agent")
    print("=" * 62)

    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
