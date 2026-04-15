"""
Parallel pipeline: fetch professor homepages → LLM summarise → write MD files.

Concurrency model
─────────────────
  • aiohttp for async HTTP (up to HTTP_CONCURRENCY simultaneous connections)
  • asyncio.to_thread to run synchronous LLM calls in a thread-pool
  • asyncio.Semaphore to cap both HTTP and LLM concurrency independently
  • asyncio.gather() runs all professors in parallel

Output per professor
────────────────────
  output/{school_slug}/{safe_name}.md
"""

import asyncio
import re
import textwrap
from datetime import date
from pathlib import Path

import aiohttp
from bs4 import BeautifulSoup

from providers.base import LLMProvider

# ── Concurrency knobs ─────────────────────────────────────────────────────────
HTTP_CONCURRENCY = 20   # simultaneous HTTP fetches
LLM_CONCURRENCY = 8     # simultaneous LLM calls (stay under rate limits)
HTTP_TIMEOUT = 12       # seconds per request

# ── Output directory ──────────────────────────────────────────────────────────
OUTPUT_ROOT = Path(__file__).parent / "output"

_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ── System prompts ────────────────────────────────────────────────────────────

_SUMMARY_SYSTEM = (
    "You are a concise academic research assistant. "
    "Given a professor's homepage content, extract their core research direction. "
    "Write ONLY in English. Be factual and specific — name the actual techniques, "
    "datasets, or application domains they work on. No filler phrases."
)

_SUMMARY_PROMPT_TMPL = """\
Professor: {name}
Affiliation: {affiliation}
Research areas (from CSRankings): {areas}

Homepage content (truncated):
{content}

---
Task 1 – SHORT SUMMARY (≤60 words):
One tight paragraph capturing the professor's main research direction.
This will be used for automated matching, so be specific and keyword-rich.

Task 2 – FULL PROFILE (150-250 words):
A more detailed description of their research themes, representative projects,
methods, and application areas. Mention any notable recent work if visible.

Respond with exactly two sections labelled:
SHORT SUMMARY:
<text>

FULL PROFILE:
<text>
"""


# ── HTML fetching ─────────────────────────────────────────────────────────────

async def _fetch_html(
    session: aiohttp.ClientSession,
    url: str,
    sem: asyncio.Semaphore,
) -> str:
    """Fetch URL with semaphore-limited concurrency. Returns raw HTML or ''."""
    if not url or url in ("NA", "N/A"):
        return ""
    async with sem:
        try:
            async with session.get(
                url,
                headers=_FETCH_HEADERS,
                timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT),
                allow_redirects=True,
                ssl=False,       # some faculty pages have expired certs
            ) as resp:
                if resp.status == 200:
                    return await resp.text(errors="replace")
                return ""
        except Exception:
            return ""


def _extract_text(html: str, max_chars: int = 8000) -> str:
    """Extract readable text from HTML, remove boilerplate."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "aside", "iframe", "noscript", "form", "button"]):
        tag.decompose()

    main = (
        soup.find("main")
        or soup.find(id=re.compile(r"main|content|body", re.I))
        or soup.find(class_=re.compile(r"main|content|body", re.I))
        or soup.body
        or soup
    )
    lines = [l.strip() for l in main.get_text("\n").splitlines() if len(l.strip()) > 25]
    text = "\n".join(lines)
    return text[:max_chars]


# ── LLM summarisation ─────────────────────────────────────────────────────────

def _parse_summaries(raw: str) -> tuple[str, str]:
    """Split the LLM response into (short_summary, full_profile)."""
    short = ""
    full = ""
    if "SHORT SUMMARY:" in raw:
        after = raw.split("SHORT SUMMARY:", 1)[1]
        if "FULL PROFILE:" in after:
            short = after.split("FULL PROFILE:", 1)[0].strip()
            full = after.split("FULL PROFILE:", 1)[1].strip()
        else:
            short = after.strip()
    else:
        # Fallback: treat entire response as short summary
        short = raw.strip()[:400]
    return short, full


async def _summarise(
    prof: dict,
    content: str,
    provider: LLMProvider,
    sem: asyncio.Semaphore,
) -> tuple[str, str]:
    """Call LLM (in thread) to get (short_summary, full_profile). Rate-limited."""
    areas_str = ", ".join(prof["areas"]) if prof["areas"] else "Unknown"

    if not content:
        short = f"{prof['name']} — homepage not accessible; research areas: {areas_str}."
        return short, ""

    prompt = _SUMMARY_PROMPT_TMPL.format(
        name=prof["name"],
        affiliation=prof["affiliation"],
        areas=areas_str,
        content=content,
    )

    async with sem:
        try:
            raw = await asyncio.to_thread(
                provider.generate, _SUMMARY_SYSTEM, prompt, 600
            )
        except Exception as e:
            short = f"{prof['name']} — LLM call failed ({type(e).__name__}); research areas: {areas_str}."
            return short, ""

    return _parse_summaries(raw)


# ── Markdown writing ──────────────────────────────────────────────────────────

def _safe_filename(name: str) -> str:
    return re.sub(r'[^\w\-]', '_', name).strip("_")


def _write_md(prof: dict, short_summary: str, full_profile: str, out_dir: Path) -> Path:
    areas_str = ", ".join(prof["areas"]) if prof["areas"] else "N/A"
    scholar_url = (
        f"https://scholar.google.com/citations?user={prof['scholarid']}"
        if prof.get("scholarid") and prof["scholarid"] != "NOSCHOLARPAGE"
        else ""
    )

    lines = [
        f"# {prof['name']}",
        "",
        f"**Affiliation**: {prof['affiliation']}  ",
        f"**Homepage**: {prof.get('homepage', 'N/A')}  ",
    ]
    if scholar_url:
        lines.append(f"**Google Scholar**: {scholar_url}  ")
    lines += [
        f"**Research Areas**: {areas_str}",
        "",
        "---",
        "",
        "## Quick Summary",
        "",
        short_summary,
        "",
        "---",
        "",
        "## Research Profile",
        "",
        full_profile if full_profile else "_Homepage not accessible or no content found._",
        "",
        "---",
        "",
        f"*Last updated: {date.today().isoformat()}*",
    ]

    path = out_dir / f"{_safe_filename(prof['name'])}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ── Per-professor task ────────────────────────────────────────────────────────

async def _process_one(
    prof: dict,
    session: aiohttp.ClientSession,
    http_sem: asyncio.Semaphore,
    llm_sem: asyncio.Semaphore,
    provider: LLMProvider,
    out_dir: Path,
    counter: list,          # mutable [done, total] for progress reporting
) -> dict:
    """Fetch + summarise + save one professor. Returns summary dict."""
    html = await _fetch_html(session, prof.get("homepage", ""), http_sem)
    text = _extract_text(html)

    short_summary, full_profile = await _summarise(prof, text, provider, llm_sem)

    md_path = _write_md(prof, short_summary, full_profile, out_dir)

    counter[0] += 1
    done, total = counter[0], counter[1]
    pct = done / total * 100
    status = "✅" if html else "⚠️ "
    print(f"  {status} [{done:3d}/{total}] {pct:5.1f}%  {prof['name']}", flush=True)

    return {
        "name": prof["name"],
        "affiliation": prof["affiliation"],
        "homepage": prof.get("homepage", ""),
        "areas": prof.get("areas", []),
        "short_summary": short_summary,
        "md_path": str(md_path),
    }


# ── School index ──────────────────────────────────────────────────────────────

def _write_index(school: str, summaries: list[dict], out_dir: Path) -> Path:
    """Write index.md with a table of all professors + their short summaries."""
    lines = [
        f"# {school} — Professor Directory",
        "",
        f"Generated: {date.today().isoformat()}  ",
        f"Total: {len(summaries)} professors",
        "",
        "| Professor | Research Areas | Quick Summary |",
        "|-----------|---------------|---------------|",
    ]
    for s in sorted(summaries, key=lambda x: x["name"]):
        name_link = f"[{s['name']}](./{_safe_filename(s['name'])}.md)"
        areas = ", ".join(s["areas"][:3]) if s["areas"] else "N/A"
        summary_cell = s["short_summary"].replace("\n", " ").replace("|", "\\|")
        summary_cell = textwrap.shorten(summary_cell, width=120, placeholder="...")
        lines.append(f"| {name_link} | {areas} | {summary_cell} |")

    path = out_dir / "index.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ── Public entry point ────────────────────────────────────────────────────────

async def run_pipeline(
    professors: list[dict],
    school: str,
    provider: LLMProvider,
) -> list[dict]:
    """
    Process all professors in parallel.
    Returns list of summary dicts (one per professor).
    """
    out_dir = OUTPUT_ROOT / _safe_filename(school)
    out_dir.mkdir(parents=True, exist_ok=True)

    http_sem = asyncio.Semaphore(HTTP_CONCURRENCY)
    llm_sem = asyncio.Semaphore(LLM_CONCURRENCY)
    counter = [0, len(professors)]

    print(f"\nProcessing {len(professors)} professors in parallel "
          f"(HTTP x{HTTP_CONCURRENCY} / LLM x{LLM_CONCURRENCY})\n")

    connector = aiohttp.TCPConnector(limit=HTTP_CONCURRENCY + 5, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            _process_one(prof, session, http_sem, llm_sem, provider, out_dir, counter)
            for prof in professors
        ]
        summaries = await asyncio.gather(*tasks, return_exceptions=True)

    # Filter out exceptions (shouldn't happen but just in case)
    valid = [s for s in summaries if isinstance(s, dict)]

    index_path = _write_index(school, valid, out_dir)
    print(f"\nSaved {len(valid)} professor profiles -> {out_dir}/")
    print(f"School index -> {index_path}")

    return valid
