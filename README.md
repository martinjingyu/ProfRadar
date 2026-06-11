<div align="center">

# ProfRadar

**AI-powered professor discovery for PhD applicants**

Find the right professors to cold-email — automatically.

[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Data](https://img.shields.io/badge/Data-CSRankings-orange)](https://csrankings.org)
[![LLM](https://img.shields.io/badge/LLM-DeepSeek%20%7C%20OpenAI%20%7C%20Claude-purple)](#configuration)

</div>

---

## What it does

You give it a school and your research interests. An agent does the rest — in two parallel phases:

1. **Phase 1 — Quick summaries**: deploys up to 6 sub-agents in parallel, each reading one professor's homepage and returning a brief research summary
2. **Phase 2 — Deep research**: filters to the 5–10 best matches, then deploys up to 4 browser-capable sub-agents per professor — reading publications, lab pages, CVs, and recent papers
3. **Match report**: generates a ranked Markdown report with a personalized cold-email tip for each top match, saved to `output/<school>/match_report_<date>.md`

---

## Quick Start

```bash
git clone https://github.com/yourname/ProfRadar.git
cd ProfRadar
pip install -r requirements.txt

cp .env.example .env
# Add your API key — see Configuration below

# Option A: write your task to request.txt and run
echo "Find professors at UW-Madison matching NLP and LLM alignment" > request.txt
python run_agent.py

# Option B: pass the task directly
python run_agent.py "Find professors at CMU matching systems and distributed computing"

# Option C: interactive chat
python run_agent.py --chat
```

---

## Installation

**Requirements:** Python 3.11+

```bash
pip install -r requirements.txt
```

**Dependencies:**

| Package | Purpose |
|---------|---------|
| `openai` | LLM calls (also used for DeepSeek-compatible endpoints) |
| `anthropic` | Claude provider |
| `playwright` | Browser-based deep research (install with `playwright install chromium`) |
| `beautifulsoup4` + `lxml` | HTML parsing |
| `python-dotenv` | API key management |

---

## Configuration

Copy `.env.example` to `.env` and fill in at least one API key:

```env
# Default agent provider
AGENT_PROVIDER=deepseek          # deepseek | openai | codex

# DeepSeek (recommended — cheap and fast)
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_MODEL=deepseek-v3
DEEPSEEK_BASE_URL=https://api.deepseek.com

# OpenAI
OPENAI_API_KEY=sk-...

# Anthropic (Claude)
ANTHROPIC_API_KEY=sk-ant-...

# Codex (OpenAI agent mode — after `codex login`)
CODEX_MODEL=gpt-5.4
CODEX_BASE_URL=https://chatgpt.com/backend-api/codex

# Browser profile for authenticated sites (optional)
AGENT_BROWSER_PROFILE=default
```

---

## Usage

### Run modes

```bash
# Single task from request.txt (auto-detected if no prompt given)
python run_agent.py

# Single task from command line
python run_agent.py "Research professors at Stanford matching robotics and sim-to-real"

# Interactive multi-turn chat
python run_agent.py --chat

# Refresh CSRankings data before starting
python run_agent.py --update-db

# Resume a previous session
python run_agent.py --resume <session-id>

# Override provider or model
python run_agent.py --provider openai --model gpt-4o "..."

# Quiet output (hide per-action trace)
python run_agent.py --quiet-actions "..."
```

### Browser profile (for sites behind login)

```bash
# Import an existing Chrome profile (cookies, sessions)
python run_agent.py --setup-browser-profile "/path/to/chrome/profile"

# Open Chrome with the agent's profile to log in manually
python run_agent.py --login-browser
```

---

## How It Works

```
request.txt / CLI prompt
         │
         ▼
   GeneralAgent (main loop, up to 50 iterations)
         │
         ├─── fetch_csrankings_data / get_professors
         │
         ├─── Phase 1: summarize_professors_parallel
         │         ThreadPoolExecutor (6 workers)
         │         Each worker: SubAgent → web_fetch → homepage summary
         │         Returns: [{name, areas, short_summary}, ...]
         │
         │    [agent filters to 5–10 best matches]
         │
         ├─── Phase 2: deep_research_professors
         │         ThreadPoolExecutor (4 workers)
         │         Each worker: SubAgent → browser → publications → CV
         │         Returns: [{recent_papers, lab_name, student_openings, contact_tip}, ...]
         │
         └─── generate_match_report → output/<school>/match_report_<date>.md
```

Each sub-agent runs independently with its own browser slot (thread-local Chrome instance, isolated user-data-dir). The main agent never blocks during parallel phases.

---

## Output

```
output/
└── University_of_Wisconsin_Madison/
    └── match_report_2026-06-10.md   ← ranked report with cold-email tips

sessions/
└── <session-id>.json                ← full conversation history (resumable)
```

**The match report includes:**
- Top 5–10 professors ranked by research fit
- Recent papers and lab name
- Whether they are taking students
- A personalized cold-email tip for each

---

## Context & Cost Management

- Tool results over 8,000 chars are automatically cached to disk; the agent reads them in chunks via `read_file(path, offset=N, max_chars=8000)`
- At 80% of the iteration budget, sub-agents are reminded to wrap up
- In the last 2 iterations, browser and fetch tools are blocked so the agent finishes cleanly
- If the main agent hits its limit, a fallback injects a finish reminder and runs up to 30 more cleanup iterations

---

## Project Structure

```
ProfRadar/
├── run_agent.py             # Entry point
├── data_manager.py          # CSRankings data fetching & caching
├── matcher.py               # Report generation helper
├── request.txt              # (create this) write your task here for auto-run
├── agent/
│   ├── agent.py             # Main agent loop
│   ├── subagent.py          # Lightweight parallel sub-agent
│   ├── cli.py               # Argument parsing & run modes
│   ├── llm.py               # LLM client (multi-provider)
│   ├── prompts.py           # System prompts
│   ├── browser_profile.py   # Chrome profile management
│   └── tools/
│       ├── browser.py       # Browser tools (thread-local slots)
│       ├── fetch.py         # web_fetch, PDF reading
│       ├── files.py         # read_file (with offset pagination), write_file, patch_file
│       ├── parallel.py      # summarize_professors_parallel, deep_research_professors
│       ├── professors.py    # get_professors, list_schools, fetch_csrankings_data
│       ├── memory.py        # Persistent memory
│       ├── compact.py       # Context compaction
│       └── skills.py        # Skills system
├── skills/
│   └── research/
│       └── professor-research/
│           └── SKILL.md     # Two-phase parallel research workflow
├── providers/               # LLM provider adapters
├── data/                    # CSRankings CSV cache (auto-created)
└── output/                  # Generated reports (auto-created)
```

---

## Supported Regions

| Region | Code |
|--------|------|
| United States | US |
| China | CN |
| United Kingdom | GB |
| Canada | CA |
| Australia | AU |
| Switzerland | CH |
| Singapore | SG |

---

## Data Source

Faculty data comes from **[CSRankings](https://csrankings.org)** by Emery Berger — the most widely used metric-based ranking of CS research institutions. The raw CSV files are fetched from the [GitHub repository](https://github.com/emeryberger/CSrankings) and cached locally. Run `python run_agent.py --update-db` to refresh.

---

## License

MIT
