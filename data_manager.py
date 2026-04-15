"""
CSRankings data fetching, caching and parsing.

Remote source: https://github.com/emeryberger/CSrankings (gh-pages branch)

Files we need
─────────────
  csrankings-a.csv … csrankings-z.csv   faculty list (name, affiliation, homepage, scholarid)
  generated-author-info.csv             research area scores per faculty member
  institutions.csv                      canonical school list (institution, region, countryabbrv)
"""

import csv
import io
import json
import string
import time
from collections import defaultdict
from pathlib import Path

import requests

# ── Constants ─────────────────────────────────────────────────────────────────

RAW_BASE = "https://raw.githubusercontent.com/emeryberger/CSrankings/gh-pages"
DATA_DIR = Path(__file__).parent / "data"
META_FILE = DATA_DIR / "_meta.json"

LETTER_FILES = [f"csrankings-{c}.csv" for c in string.ascii_lowercase]
EXTRA_FILES = ["generated-author-info.csv", "institutions.csv"]
ALL_FILES = LETTER_FILES + EXTRA_FILES

# Human-readable labels for CSRankings area codes
AREA_LABELS: dict[str, str] = {
    "ai": "AI",
    "vision": "Computer Vision",
    "mlmining": "Machine Learning",
    "nlp": "NLP",
    "speech": "Speech",
    "arch": "Computer Architecture",
    "comm": "Networks",
    "sec": "Security",
    "mod": "EDA/Modeling",
    "da": "Design Automation",
    "embed": "Embedded Systems",
    "hpc": "High-Performance Computing",
    "mobile": "Mobile Computing",
    "metrics": "Metrics",
    "ops": "Operating Systems",
    "pl": "Programming Languages",
    "soft": "Software Engineering",
    "act": "Algorithms & Complexity",
    "crypt": "Cryptography",
    "log": "Logic & Verification",
    "bio": "Computational Biology",
    "graph": "Computer Graphics",
    "econ": "Economics & Computation",
    "iot": "IoT",
    "robotics": "Robotics",
    "vis": "Visualization",
    "web": "Web & Information Systems",
    "real": "Real-Time Systems",
    "csed": "CS Education",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _raw_url(filename: str) -> str:
    return f"{RAW_BASE}/{filename}"


def _fetch_text(url: str, timeout: int = 30) -> str:
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def _save(filename: str, text: str) -> None:
    (DATA_DIR / filename).write_text(text, encoding="utf-8")


def _load(filename: str) -> str:
    return (DATA_DIR / filename).read_text(encoding="utf-8")


def _read_meta() -> dict:
    if META_FILE.exists():
        return json.loads(META_FILE.read_text())
    return {}


def _write_meta(meta: dict) -> None:
    META_FILE.write_text(json.dumps(meta, indent=2))


# ── Public API ────────────────────────────────────────────────────────────────

def data_exists() -> bool:
    """True if all required files are present locally."""
    return all((DATA_DIR / f).exists() for f in ALL_FILES)


def last_updated() -> str | None:
    meta = _read_meta()
    return meta.get("updated_at")


def fetch_all_data(verbose: bool = True) -> None:
    """
    Download all CSRankings CSV files from GitHub and cache them locally.
    Safe to call again — just overwrites the cache.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    for i, filename in enumerate(ALL_FILES, 1):
        url = _raw_url(filename)
        if verbose:
            print(f"  [{i:2d}/{len(ALL_FILES)}] {filename}", end=" ... ", flush=True)
        try:
            text = _fetch_text(url)
            _save(filename, text)
            if verbose:
                rows = text.count("\n")
                print(f"✅  ({rows} lines)")
        except Exception as e:
            if verbose:
                print(f"⚠️  {e}")

    _write_meta({"updated_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())})


# ── Parsing ───────────────────────────────────────────────────────────────────

def _parse_faculty() -> list[dict]:
    """Merge all csrankings-*.csv into a deduplicated list."""
    seen: set[str] = set()
    faculty: list[dict] = []

    for filename in LETTER_FILES:
        path = DATA_DIR / filename
        if not path.exists():
            continue
        reader = csv.DictReader(io.StringIO(_load(filename)))
        for row in reader:
            key = (row.get("name", "").strip(), row.get("affiliation", "").strip())
            if key in seen:
                continue
            seen.add(key)
            faculty.append({
                "name": row.get("name", "").strip(),
                "affiliation": row.get("affiliation", "").strip(),
                "homepage": row.get("homepage", "").strip(),
                "scholarid": row.get("scholarid", "").strip(),
            })

    return faculty


def _parse_areas() -> dict[str, list[str]]:
    """
    Return a dict mapping faculty name → sorted list of human-readable area labels.
    Uses generated-author-info.csv which has cumulative publication scores per area.
    """
    path = DATA_DIR / "generated-author-info.csv"
    if not path.exists():
        return {}

    # Accumulate area counts per person; keep areas with any count > 0
    name_areas: dict[str, set[str]] = defaultdict(set)
    reader = csv.DictReader(io.StringIO(_load("generated-author-info.csv")))
    for row in reader:
        name = row.get("name", "").strip()
        area = row.get("area", "").strip().lower()
        try:
            count = float(row.get("adjustedcount", 0) or 0)
        except ValueError:
            count = 0
        if name and area and count > 0:
            label = AREA_LABELS.get(area, area)
            name_areas[name].add(label)

    return {name: sorted(areas) for name, areas in name_areas.items()}


def get_schools() -> list[str]:
    """
    Return a sorted list of institution names from institutions.csv.
    Only returns US institutions (countryabbrv == 'US') to keep the list manageable.
    """
    path = DATA_DIR / "institutions.csv"
    if not path.exists():
        raise FileNotFoundError("institutions.csv not found — run fetch_all_data() first.")

    schools: list[str] = []
    reader = csv.DictReader(io.StringIO(_load("institutions.csv")))
    for row in reader:
        country = row.get("countryabbrv", "").strip().upper()
        if country == "US":
            name = row.get("institution", "").strip()
            if name:
                schools.append(name)

    return sorted(set(schools))


def get_professors(school_name: str) -> list[dict]:
    """
    Return all faculty at *school_name* (exact match against the affiliation field).
    Each dict has: name, affiliation, homepage, scholarid, areas (list[str]).
    """
    faculty = _parse_faculty()
    areas_map = _parse_areas()

    school_lower = school_name.strip().lower()
    result = []

    for prof in faculty:
        if prof["affiliation"].lower() == school_lower:
            prof["areas"] = areas_map.get(prof["name"], [])
            result.append(prof)

    return result
