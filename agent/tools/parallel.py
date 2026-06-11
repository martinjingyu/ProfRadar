from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from .registry import json_result, registry


_QUICK_SUMMARY_TOOLS = ["web_fetch", "read_url_pdf", "read_pdf", "save_research_notes"]

_DEEP_RESEARCH_TOOLS = [
    "web_fetch", "read_url_pdf", "read_pdf", "save_research_notes",
    "browser_navigate", "browser_snapshot", "browser_click", "browser_type",
    "browser_press_key", "browser_scroll", "browser_back",
    "google_search", "bing_search",
]

_QUICK_SYSTEM = """You are a professor research assistant. Research a professor and return a JSON summary.

Given a professor's name, affiliation, homepage URL, and CSRankings research areas, read their homepage (and optionally their CV or papers page if linked) and build a summary.

Return ONLY a JSON object with these fields:
- name: professor's full name
- affiliation: their university/institution
- homepage: their homepage URL
- areas: list of research area strings (from CSRankings + what you find on homepage)
- short_summary: 1-2 sentences describing their specific research focus and notable techniques/projects

If the homepage is inaccessible, use only the CSRankings area data and note "homepage inaccessible" in short_summary.
Return ONLY the JSON object, no other text."""

_DEEP_SYSTEM = """You are a professor research assistant doing deep research on a professor to help a PhD applicant.

Given a professor's initial summary and the applicant's research interests, dig deeper: read their publications page, recent papers, lab page, and CV if available.

Return ONLY a JSON object with these fields:
- name: professor's full name
- affiliation: their university/institution
- homepage: their homepage URL
- areas: list of research area strings
- short_summary: 2-3 sentences describing their research focus, specific techniques, recent notable work
- recent_papers: list of 2-4 recent paper titles (if found, else empty list)
- lab_name: their lab name if applicable (or null)
- student_openings: true, false, or "unknown"
- contact_tip: one sentence on how to cold-email this professor based on their specific focus

Return ONLY the JSON object, no other text."""


def _parse_json_from_text(text: str) -> dict | None:
    try:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group())
    except (json.JSONDecodeError, AttributeError):
        pass
    return None


def _run_quick_summary(prof: dict, model: str | None, provider: str | None) -> dict:
    from ..subagent import SubAgent

    agent = SubAgent(
        allowed_tools=_QUICK_SUMMARY_TOOLS,
        model=model,
        provider=provider,
        system_prompt=_QUICK_SYSTEM,
    )
    task = (
        f"Research Professor {prof.get('name', 'Unknown')} at {prof.get('affiliation', '')}.\n"
        f"Homepage: {prof.get('homepage') or 'N/A'}\n"
        f"CSRankings areas: {', '.join(prof.get('areas', []))}\n\n"
        f"Read their homepage and return a JSON summary."
    )
    result_text = agent.run(task, max_iters=8)
    parsed = _parse_json_from_text(result_text)
    if parsed:
        parsed.setdefault("name", prof.get("name", ""))
        parsed.setdefault("affiliation", prof.get("affiliation", ""))
        parsed.setdefault("homepage", prof.get("homepage", ""))
        parsed.setdefault("areas", prof.get("areas", []))
        return parsed
    return {
        "name": prof.get("name", ""),
        "affiliation": prof.get("affiliation", ""),
        "homepage": prof.get("homepage", ""),
        "areas": prof.get("areas", []),
        "short_summary": (
            f"Research areas: {', '.join(prof.get('areas', []))}. (Homepage could not be summarized.)"
        ),
    }


def _run_deep_research(prof: dict, interests: str, model: str | None, provider: str | None) -> dict:
    from ..subagent import SubAgent

    agent = SubAgent(
        allowed_tools=_DEEP_RESEARCH_TOOLS,
        model=model,
        provider=provider,
        system_prompt=_DEEP_SYSTEM,
    )
    task = (
        f"Do deep research on Professor {prof.get('name', 'Unknown')} at {prof.get('affiliation', '')}.\n"
        f"Homepage: {prof.get('homepage') or 'N/A'}\n"
        f"Initial summary: {prof.get('short_summary', '')}\n"
        f"Research areas: {', '.join(prof.get('areas', []))}\n"
        f"Applicant's interests: {interests}\n\n"
        f"Read their homepage thoroughly. Check publications, lab page, CV if available. "
        f"Focus on specific research techniques, recent work, and alignment with applicant's interests. "
        f"Return a comprehensive JSON summary."
    )
    result_text = agent.run(task, max_iters=15)
    parsed = _parse_json_from_text(result_text)
    if parsed:
        parsed.setdefault("name", prof.get("name", ""))
        parsed.setdefault("affiliation", prof.get("affiliation", ""))
        parsed.setdefault("homepage", prof.get("homepage", ""))
        parsed.setdefault("areas", prof.get("areas", []))
        return parsed
    return {**prof, "short_summary": prof.get("short_summary", "") + " (deep research could not be completed)"}


def _h_summarize_professors_parallel(args: dict, _rt: dict) -> str:
    professors = args.get("professors", [])
    max_workers = min(int(args.get("max_workers", 6)), 10)
    model = args.get("model") or None
    provider = args.get("provider") or None

    if not professors:
        return json_result(success=False, error="No professors provided")

    summaries: list[dict] = []
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=min(max_workers, len(professors))) as pool:
        futures = {
            pool.submit(_run_quick_summary, prof, model, provider): prof.get("name", f"prof_{i}")
            for i, prof in enumerate(professors)
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                summaries.append(future.result())
            except Exception as exc:
                errors.append(f"{name}: {exc}")

    return json_result(
        success=True,
        summaries=summaries,
        count=len(summaries),
        errors=errors if errors else None,
    )


def _h_deep_research_professors(args: dict, _rt: dict) -> str:
    professors = args.get("professors", [])
    interests = args.get("interests", "")
    max_workers = min(int(args.get("max_workers", 4)), 8)
    model = args.get("model") or None
    provider = args.get("provider") or None

    if not professors:
        return json_result(success=False, error="No professors provided")

    summaries: list[dict] = []
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=min(max_workers, len(professors))) as pool:
        futures = {
            pool.submit(_run_deep_research, prof, interests, model, provider): prof.get("name", f"prof_{i}")
            for i, prof in enumerate(professors)
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                summaries.append(future.result())
            except Exception as exc:
                errors.append(f"{name}: {exc}")

    return json_result(
        success=True,
        summaries=summaries,
        count=len(summaries),
        errors=errors if errors else None,
    )


registry.register("summarize_professors_parallel", {
    "description": (
        "Phase 1 of professor research: launch parallel sub-agents that each read a professor's "
        "homepage and return a quick summary. Call this after get_professors() with the full or "
        "area-filtered list. Returns summaries with: name, affiliation, homepage, areas, short_summary."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "professors": {
                "type": "array",
                "description": "List of professor dicts from get_professors(), each with name, affiliation, homepage, areas.",
                "items": {"type": "object"},
            },
            "max_workers": {
                "type": "integer",
                "description": "Max parallel sub-agents (default 6, cap 10).",
                "default": 6,
            },
            "model": {"type": "string", "description": "Model override for sub-agents (optional)."},
            "provider": {"type": "string", "description": "Provider override for sub-agents (optional)."},
        },
        "required": ["professors"],
    },
}, _h_summarize_professors_parallel)


registry.register("deep_research_professors", {
    "description": (
        "Phase 2 of professor research: launch parallel sub-agents to do deep research on each selected "
        "professor. Each sub-agent reads the homepage, publications page, lab page, and CV/PDF in depth. "
        "Call this after filtering Phase 1 summaries to the most relevant professors (typically 5-10). "
        "Returns enhanced summaries with recent_papers, lab_name, student_openings, and contact_tip."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "professors": {
                "type": "array",
                "description": "Filtered list of professor dicts to research in depth (from Phase 1 or get_professors()).",
                "items": {"type": "object"},
            },
            "interests": {
                "type": "string",
                "description": "User's research interests — sub-agents focus research on alignment with these.",
            },
            "max_workers": {
                "type": "integer",
                "description": "Max parallel sub-agents (default 4, cap 8).",
                "default": 4,
            },
            "model": {"type": "string", "description": "Model override for sub-agents (optional)."},
            "provider": {"type": "string", "description": "Provider override for sub-agents (optional)."},
        },
        "required": ["professors", "interests"],
    },
}, _h_deep_research_professors)
