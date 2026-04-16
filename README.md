<div align="center">

# 📡 ProfRadar

**AI-powered professor discovery for PhD applicants**

Find the right professors to cold-email — automatically.

[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Data](https://img.shields.io/badge/Data-CSRankings-orange)](https://csrankings.org)
[![LLM](https://img.shields.io/badge/LLM-GPT%20%7C%20Claude%20%7C%20Gemini-purple)](#supported-providers)

</div>

---

## What it does

You tell it a region, a school, and your research interests. It does the rest:

1. **Fetches** the full faculty list from [CSRankings](https://csrankings.org) (live data, 7 regions supported)
2. **Scrapes** every professor's homepage — in parallel
3. **Summarizes** each professor's research with an LLM
4. **Generates** a ranked list of professors you should actually email, with a personalized tip for each

```
📚 Found 87 professors (Carnegie Mellon University)
⚡ Processing in parallel (HTTP×20 / LLM×8)

  ✅ [ 1/50]   2.0%  Yonatan Bisk
  ✅ [ 2/50]   4.0%  Graham Neubig
  ✅ [ 3/50]   6.0%  Maarten Sap
  ...

### 1. Graham Neubig
**Research focus**: Multilingual NLP, low-resource languages, code generation with LLMs
**Why it fits**: Directly works on LLM-based code generation and multilingual transfer — exact overlap with your stated interests
**Email tip**: Mention his EMNLP 2024 paper on cross-lingual prompting; ask about the xCodeEval benchmark
```

---

## Quick Start

```bash
git clone https://github.com/yourname/ProfRadar.git
cd ProfRadar
pip install -r requirements.txt

cp .env.example .env
# Add your API key (OpenAI / Claude / Gemini / Azure)

python main.py --limit 50
```

Your choices are remembered — next run just press Enter to reuse the same region, school, and interests.

---

## Installation

**Requirements:** Python 3.11+

```bash
pip install -r requirements.txt
```

**Dependencies:**
| Package | Purpose |
|---------|---------|
| `aiohttp` | Parallel homepage scraping |
| `beautifulsoup4` + `lxml` | HTML parsing |
| `openai` / `anthropic` / `google-genai` | LLM providers |
| `python-dotenv` | API key management |

---

## Configuration

Copy `.env.example` to `.env` and fill in **one or more** API keys:

```env
# OpenAI
OPENAI_API_KEY=sk-...

# Anthropic (Claude)
ANTHROPIC_API_KEY=sk-ant-...

# Google Gemini
GEMINI_API_KEY=AIza...

# Azure OpenAI
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://YOUR_RESOURCE.openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-02-01
AZURE_OPENAI_DEPLOYMENT=your-deployment-name

# Default provider
DEFAULT_PROVIDER=openai
```

---

## Usage

```bash
# Basic (uses DEFAULT_PROVIDER from .env)
python main.py

# Limit to 50 professors (recommended for first run)
python main.py --limit 50

# Choose provider and model
python main.py --provider openai --model gpt-4o-mini --limit 50
python main.py --provider anthropic --limit 50
python main.py --provider gemini --model gemini-2.0-flash --limit 50
python main.py --provider azure --limit 50

# Refresh CSRankings data
python main.py --update

# Clear saved school/interests (re-enter everything)
python main.py --reset
```

### Supported Providers

| Provider | Recommended Model | Notes |
|----------|------------------|-------|
| OpenAI | `gpt-4o-mini` | Best cost/quality balance |
| Anthropic | `claude-opus-4-6` | Highest quality summaries |
| Google | `gemini-2.0-flash` | Fast and cheap |
| Azure OpenAI | your deployment | Enterprise/private deployments |

---

## Output

All results are saved under `output/{school}/`:

```
output/
└── Carnegie_Mellon_University/
    ├── Graham_Neubig.md          # Individual professor profile
    ├── Yonatan_Bisk.md
    ├── ...
    ├── index.md                  # Full school directory (table)
    └── match_report_2026-04-14.md  # Your personalized recommendations
```

**Each professor profile contains:**
- Research areas (from CSRankings publication data)
- 60-word quick summary (used for matching)
- 200-word full research profile

**The match report ranks** the top 8 professors by fit and gives you a concrete cold-email tip for each.

---

## How It Works

```
CSRankings GitHub ──► data_manager.py ──► professor list
                                               │
                               ┌───────────────┤
                               │ asyncio.gather (parallel)
                               │
                     ┌─────────▼──────────┐
                     │  aiohttp fetch     │  ← up to 20 concurrent
                     │  homepage HTML     │
                     └─────────┬──────────┘
                               │
                     ┌─────────▼──────────┐
                     │  LLM summarize     │  ← up to 8 concurrent
                     │  60w + 200w        │
                     └─────────┬──────────┘
                               │
                     ┌─────────▼──────────┐
                     │  write .md files   │
                     └─────────┬──────────┘
                               │
                     ┌─────────▼──────────┐
                     │  matcher: rank     │  ← 1 LLM call with all summaries
                     │  top 8 by fit      │
                     └────────────────────┘
```

Fetching and summarizing are fully parallel — 50 professors typically finish in **2–4 minutes**.

---

## Tips

- **Start with `--limit 50`** to keep costs and time manageable. A full department (100+ professors) can be processed in one shot once you know the tool works.
- **Re-run freely** — existing `.md` files are overwritten, the match report gets a date stamp so old ones are preserved.
- **Switch schools without losing interests** — just press `c` at the school prompt, your interests stay saved.
- **gpt-4o-mini** is the cheapest option and works well for the summarization step. The final matching call is just one request regardless of professor count.

---

## Project Structure

```
ProfRadar/
├── main.py                  # Entry point & orchestration
├── data_manager.py          # CSRankings data fetching & caching
├── school_selector.py       # Interactive school picker
├── professor_pipeline.py    # Async parallel scrape + summarize + write
├── matcher.py               # Final LLM matching & ranking
├── providers/
│   ├── base.py              # LLMProvider interface
│   ├── anthropic_provider.py
│   ├── openai_provider.py
│   ├── azure_openai_provider.py
│   └── gemini_provider.py
├── data/                    # CSRankings CSV cache (auto-created)
├── output/                  # Generated profiles & reports (auto-created)
├── requirements.txt
└── .env.example
```

---

## Supported Regions

| Region | Country Code |
|--------|-------------|
| United States | US |
| China | CN |
| United Kingdom | GB |
| Canada | CA |
| Australia | AU |
| Switzerland | CH |
| Singapore | SG |

Region is selected interactively at startup and remembered for future runs.

---

## Data Source

Faculty data comes from **[CSRankings](https://csrankings.org)** by Emery Berger — the most widely used metric-based ranking of CS research institutions. The raw CSV files are fetched directly from the [GitHub repository](https://github.com/emeryberger/CSrankings) and cached locally. Run `python main.py --update` to refresh.

---

## Contributing

PRs welcome. Some ideas:

- [ ] Cache scraped homepages to avoid re-fetching on re-runs
- [ ] Filter professors by CSRankings area before scraping (e.g., only ML/NLP profs)
- [ ] Export match report as PDF
- [x] Support non-US schools — US, China, UK, Canada, Australia, Switzerland, Singapore
- [ ] Add a web UI

---

## License

MIT
