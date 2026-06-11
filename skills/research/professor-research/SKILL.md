---
name: professor-research
description: Autonomously research professors at a target university from CSRankings — deploy parallel sub-agents for quick summaries then deep research, match to user interests, and generate a ranked cold-email report.
---

## Overview

Use this skill when the user wants to find PhD advisors at a specific university whose research aligns with their interests. The workflow runs in two parallel phases: Phase 1 quickly summarizes each professor's homepage, Phase 2 does deep research on the best matches. Output is a ranked Markdown report saved to `output/<school>/match_report_<date>.md`.

## Two Query Modes

### Mode A — "Find matching advisors" (standard)
Full two-phase parallel workflow. Follow the Step-by-Step below.

### Mode B — "Look up a specific person"
User asks about a named individual (e.g. "Is Professor X at Y?"). Use abbreviated flow:
1. Call `get_professors(school)` — check the CSRankings faculty list (1 tool call).
2. If found: call `web_fetch(homepage)` and build a summary. Report findings.
3. If NOT found: report clearly (likely a student/postdoc not in CSRankings). Do NOT burn iterations on generic web searches.

## Prerequisites

- CSRankings data must be downloaded (call `fetch_csrankings_data` once if missing).
- Know the exact university name. Use `list_schools` to confirm.
- Have the user's research interests before starting.

## Step-by-Step

### Step 1 — Clarify inputs (if not already provided)

Ask the user for:
- **School**: target university (e.g. "University of Wisconsin - Madison")
- **Interests**: specific research topics (e.g. "NLP, LLM alignment, code generation, RAG")
- **Extra requirements** (optional): prefers small lab, strong industry connections, open-source focus, etc.

### Step 2 — Bootstrap data

```
fetch_csrankings_data()              ← only if first run
list_schools(region="United States") ← confirm exact spelling
```

### Step 3 — Get professor list

```
get_professors(school="<exact name>")
```

Review: total count, areas distribution. Note which areas overlap user interests — filter to those for Phase 1 if the list is large (> 30 professors).

### Step 4 — Phase 1: Parallel quick summaries

```
summarize_professors_parallel(
  professors=[...],   ← full list or area-filtered subset
  max_workers=6       ← adjust based on list size; cap at 10
)
```

Each sub-agent reads one professor's homepage and returns:
`{name, affiliation, homepage, areas, short_summary}`

After Phase 1 completes:
- Review all summaries
- Select **5–10 professors** whose research most closely aligns with user interests
- These become the input for Phase 2

### Step 5 — Phase 2: Parallel deep research

```
deep_research_professors(
  professors=[...],    ← filtered list from Phase 1 (5–10 professors)
  interests="...",     ← user's interests string
  max_workers=4        ← browser-heavy; cap at 6
)
```

Each sub-agent does deep research: reads homepage fully, checks publications page, lab page, and CV/PDF if available. Returns enhanced summary:
`{name, affiliation, homepage, areas, short_summary, recent_papers, lab_name, student_openings, contact_tip}`

### Step 6 — Pre-flight dependency check

Before calling `generate_match_report`, check if the required package is available:

```python
# In your head: verify anthropic is importable
# If not, skip directly to the manual fallback below.
```

### Step 7 — Generate match report

```
generate_match_report(
  summaries=[...],   ← Phase 2 deep summaries
  interests="...",   ← user's interests string
  school="..."
)
```

Returns the full report text and `saved_to` path.

**Fallback** (if `generate_match_report` fails due to missing dependencies):

1. **Rank the professors** by relevance to user interests (score 1–10).
2. **Build the report content** as a string using the template at `templates/match_report_manual.md`. Fill in all fields from the Phase 2 summaries.
3. **Write the file** with `write_file(path=..., content=...)` — path should be `output/<school>/match_report_<date>.md`.
4. **Verify** by calling `read_file(path)` to confirm the report was written correctly.

The template includes sections for: score, areas, summary, fit reason, recent papers, lab name, student openings, contact tip, and homepage. If a field is missing from a summary, write "Not found" rather than leaving a placeholder.

### Step 7 — Handle mid-conversation pivots

If the user changes their research interests mid-conversation (e.g., "I don't want to do X anymore"):

1. **Re-read the existing report** from disk using `read_file(path)` to get the current state.
2. **Re-filter the Phase 2 summaries** — remove professors whose work is primarily in the area the user wants to avoid.
3. **Re-rank remaining professors** based on the updated interests.
4. **Rewrite the report** with the updated rankings and a note about the pivot.
5. **Respond** explaining what changed and why.

If the pivot is significant enough that no professors remain from the original set, inform the user and suggest starting fresh with a new school or broader criteria.

### Step 8 — Respond to user

Call `respond_to_user` with:
- Report path (`saved_to`)
- Preview of top 3–5 matches: name, research focus, why it fits, contact tip
- Note any professors whose homepages were inaccessible
- If a mid-conversation pivot occurred, explain what changed

## Critical Guardrails

### Never use generic web search as a first step
- **Never** call `google_search`, `bing_search`, or `baidu_search` to find professors.
- Always start with CSRankings tools: `get_professors(school)`.
- Generic search is expensive and rarely finds what CSRankings already has.

### Don't chase individuals not in CSRankings
- If a named person is not in the faculty list, they are likely a student/postdoc. Report this and move on.

### Phase 1 before Phase 2
- Always run Phase 1 first to filter before committing to expensive Phase 2 deep research.
- If Phase 1 returns too few useful summaries, widen the area filter or lower the threshold.

## Context Management

- Sub-agents in Phase 1 and Phase 2 manage their own context independently — no compaction needed during parallel phases.
- After Phase 2 returns, if the summaries list is large (> 8000 chars), the result may be spilled to disk — use `read_file(path)` to access it.
- Call `compact_context(focus="professor summaries and user interests")` between phases if the main context grows large.

## Output Files

```
output/
  <school_slug>/
    match_report_<date>.md    ← ranked report with cold-email tips
```

## Troubleshooting

| Problem | Action |
|---------|--------|
| "CSRankings data not found" | Call `fetch_csrankings_data` |
| 0 professors found | Call `list_schools` — school name likely wrong |
| Phase 1 returns many "homepage inaccessible" | Lower max_workers; some sites block parallel fetches. Or run web_fetch manually on the key professors. |
| Phase 2 sub-agent errors | Check `errors` field in result; proceed with successful summaries |
| generate_match_report fails with ModuleNotFoundError | Install `pip install anthropic` or write report manually with write_file |
| generate_match_report fails with auth error | Check `.env` for ANTHROPIC_API_KEY / OPENAI_API_KEY |
| Context too large after Phase 2 | Call `compact_context(focus="summaries and interests")` before generate_match_report |
| Iteration budget exhausted | Use whatever summaries you have — even 5 good ones are enough for a useful report |
