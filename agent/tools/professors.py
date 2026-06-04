"""
Professor data tools — wraps ProfRadar's data_manager and matcher.

Tools registered:
  fetch_csrankings_data  — download / refresh CSRankings CSV cache
  list_schools           — list available schools (optionally filtered by region)
  get_professors         — given a school name, return professor list from CSRankings
  generate_match_report  — rank professor summaries against user interests and save a report

Note: actual per-professor research (homepage fetch, PDF reading) is done by the agent
using web_fetch, read_url_pdf, and read_pdf tools, one professor at a time.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date
from pathlib import Path

from .registry import json_result, registry

_PROFRADAR_ROOT = Path(__file__).resolve().parents[2]


def _ensure_profradar_path() -> None:
    root = str(_PROFRADAR_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def _auto_build_provider(provider_name: str | None, model: str | None):
    _ensure_profradar_path()
    if not provider_name:
        if os.getenv("ANTHROPIC_API_KEY"):
            provider_name = "anthropic"
        elif os.getenv("OPENAI_API_KEY"):
            provider_name = "openai"
        elif os.getenv("GEMINI_API_KEY"):
            provider_name = "gemini"
        else:
            provider_name = os.getenv("DEFAULT_PROVIDER", "openai")

    p = provider_name.lower()
    if p == "anthropic":
        from providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider(model=model)
    if p == "openai":
        from providers.openai_provider import OpenAIProvider
        return OpenAIProvider(model=model)
    if p == "gemini":
        from providers.gemini_provider import GeminiProvider
        return GeminiProvider(model=model)
    if p == "azure":
        from providers.azure_openai_provider import AzureOpenAIProvider
        return AzureOpenAIProvider(deployment=model)
    from providers.openai_provider import OpenAIProvider
    return OpenAIProvider(model=model)


# ── Tool handlers ─────────────────────────────────────────────────────────────

def _fetch_csrankings_data(args: dict, runtime: dict) -> str:
    _ensure_profradar_path()
    try:
        import data_manager as dm
        print("Downloading CSRankings data from GitHub...")
        dm.fetch_all_data(verbose=True)
        return json_result(success=True, message="CSRankings data downloaded successfully.")
    except Exception as exc:
        return json_result(success=False, error=f"{type(exc).__name__}: {exc}")


def _list_schools(args: dict, runtime: dict) -> str:
    region = args.get("region") or None
    _ensure_profradar_path()
    try:
        import data_manager as dm
        if not dm.data_exists():
            return json_result(
                success=False,
                error="CSRankings data not found. Call fetch_csrankings_data first.",
            )
        schools = dm.get_schools(region=region)
        return json_result(success=True, region=region, count=len(schools), schools=schools)
    except Exception as exc:
        return json_result(success=False, error=f"{type(exc).__name__}: {exc}")


def _get_professors(args: dict, runtime: dict) -> str:
    school = str(args.get("school") or "").strip()
    if not school:
        return json_result(success=False, error="school is required")
    _ensure_profradar_path()
    try:
        import data_manager as dm
        if not dm.data_exists():
            return json_result(
                success=False,
                error="CSRankings data not found. Call fetch_csrankings_data first.",
            )
        professors = dm.get_professors(school)
        if not professors:
            all_schools = dm.get_schools()
            school_lower = school.lower()
            hints = [s for s in all_schools if school_lower in s.lower()][:5]
            hint_msg = f" Did you mean one of: {hints}?" if hints else ""
            return json_result(
                success=False,
                error=f"No professors found for '{school}'. The name must match exactly.{hint_msg}",
            )
        return json_result(
            success=True,
            school=school,
            count=len(professors),
            professors=professors,
        )
    except Exception as exc:
        return json_result(success=False, error=f"{type(exc).__name__}: {exc}")


def _generate_match_report(args: dict, runtime: dict) -> str:
    """Rank professor summaries against user interests via LLM and save a Markdown report."""
    summaries_raw = args.get("summaries")
    interests = str(args.get("interests") or "").strip()
    school = str(args.get("school") or "unknown").strip()
    provider_name = args.get("provider") or None
    model = args.get("model") or None

    if not summaries_raw:
        return json_result(success=False, error="summaries is required (list of dicts with at least name and short_summary)")
    if not interests:
        return json_result(success=False, error="interests is required")

    _ensure_profradar_path()
    try:
        summaries = summaries_raw if isinstance(summaries_raw, list) else json.loads(summaries_raw)
        provider = _auto_build_provider(provider_name, model)

        from matcher import match_professors
        report = match_professors(summaries, interests, provider)

        school_slug = re.sub(r"[^\w\-]", "_", school).strip("_") or "unknown"
        out_dir = _PROFRADAR_ROOT / "output" / school_slug
        out_dir.mkdir(parents=True, exist_ok=True)
        report_path = out_dir / f"match_report_{date.today().isoformat()}.md"
        report_path.write_text(report, encoding="utf-8")

        return json_result(
            success=True,
            school=school,
            report=report,
            saved_to=str(report_path),
        )
    except Exception as exc:
        import traceback
        return json_result(
            success=False,
            error=f"{type(exc).__name__}: {exc}",
            detail=traceback.format_exc()[-2000:],
        )


# ── Register tools ────────────────────────────────────────────────────────────

registry.register(
    "fetch_csrankings_data",
    {
        "description": (
            "Download (or refresh) all CSRankings CSV files from GitHub and cache them locally. "
            "Must be called at least once before get_professors or list_schools will work."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    _fetch_csrankings_data,
)

registry.register(
    "list_schools",
    {
        "description": (
            "List schools available in the CSRankings dataset. "
            "Use this to find the exact spelling of a university name before calling get_professors."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "region": {
                    "type": "string",
                    "description": (
                        "Optional region filter. One of: 'United States', 'China', "
                        "'United Kingdom', 'Canada', 'Australia', 'Switzerland', 'Singapore'. "
                        "Omit to list all regions."
                    ),
                }
            },
            "required": [],
        },
    },
    _list_schools,
)

registry.register(
    "get_professors",
    {
        "description": (
            "Return all professors at a given school from CSRankings data. "
            "Each professor dict contains: name, affiliation, homepage, scholarid, areas (list of research area labels). "
            "The school name must match exactly — use list_schools first if unsure of the exact spelling."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "school": {
                    "type": "string",
                    "description": "Exact school name as it appears in CSRankings (e.g. 'Carnegie Mellon University').",
                }
            },
            "required": ["school"],
        },
    },
    _get_professors,
)

registry.register(
    "generate_match_report",
    {
        "description": (
            "Given a list of professor summaries and the user's research interests, "
            "use an LLM to rank the top professors by fit and generate personalized cold-email tips. "
            "Each summary dict must have at least: name, areas (list), short_summary (string). "
            "Saves the report to output/<school>/match_report_<date>.md and returns the full report text."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "summaries": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": (
                        "List of professor summary dicts. Required fields per item: "
                        "name (str), areas (list[str]), short_summary (str). "
                        "Build this list as you research each professor."
                    ),
                },
                "interests": {
                    "type": "string",
                    "description": "User's research interests and any additional requirements.",
                },
                "school": {
                    "type": "string",
                    "description": "School name (used for output file path).",
                },
                "provider": {
                    "type": "string",
                    "description": "LLM provider: 'anthropic', 'openai', 'gemini', 'azure'. Auto-detected from env if omitted.",
                },
                "model": {
                    "type": "string",
                    "description": "Model name override. Uses provider default if omitted.",
                },
            },
            "required": ["summaries", "interests"],
        },
    },
    _generate_match_report,
)
