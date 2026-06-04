---
name: professor-research
description: Autonomously research professors at a target university from CSRankings — read their homepages and papers, build summaries, match to user interests, and generate a ranked cold-email report.
---

## Overview

Use this skill when the user wants to find PhD advisors at a specific university whose research aligns with their interests. You research each professor yourself by reading their homepage, lab page, and/or CV PDF. The output is a ranked Markdown report with personalized cold-email tips, saved to `output/<school>/match_report_<date>.md`.

## Prerequisites

- CSRankings data must be downloaded locally (call `fetch_csrankings_data` once if missing).
- Know the exact university name as it appears in CSRankings. Use `list_schools` to confirm.
- Have the user's research interests before starting.

## Step-by-Step

### Step 1 — Clarify inputs (if not already provided)

Ask the user for:
- **School**: target university (e.g. "University of Wisconsin - Madison")
- **Interests**: specific research topics (e.g. "NLP, LLM alignment, code generation, RAG")
- **Extra requirements** (optional): prefers small lab, open-source focus, strong theory background, etc.

### Step 2 — Bootstrap data

```
fetch_csrankings_data()     ← only if first run
list_schools(region="United States")   ← confirm exact spelling
```

### Step 3 — Get professor list

```
get_professors(school="<exact name>")
```

Review: count, areas distribution. Note which professors have overlapping areas with user interests — research those first.

### Step 4 — Deep research loop (per professor)

For each professor, starting with the most area-relevant ones:

**4a. Read the homepage**
```
web_fetch(url=professor["homepage"], max_chars=10000)
```
Look for: research statement, current projects, recent papers, student info, lab focus.

**4b. Dig deeper if needed**
If the homepage links to:
- A CV PDF → `read_url_pdf(url=cv_link)`
- A papers/publications page → `web_fetch(url=papers_page)`
- A lab group page → `web_fetch(url=lab_page)`

**4c. Build a summary dict**
After reading, synthesize:
```json
{
  "name": "...",
  "affiliation": "...",
  "homepage": "...",
  "areas": ["...", "..."],
  "short_summary": "1-2 sentences: core research direction, specific techniques/topics, any notable recent work."
}
```

**4d. Error handling**
- Homepage 404/timeout → try Google Scholar: `web_fetch(url="https://scholar.google.com/citations?user=<scholarid>")`
- No homepage URL → web search by name + school
- Blank page → use only CSRankings areas for the summary

**Goal**: aim for **10–20 good summaries**. Prioritize quality over quantity — skip professors with zero homepage content if you already have enough matches.

### Step 5 — Generate match report

```
generate_match_report(
  summaries=[...],     ← the list you built in step 4
  interests="...",     ← user's interests string
  school="..."
)
```

Returns the full report text and `saved_to` path.

### Step 6 — Respond to user

Call `respond_to_user` with:
- Report path (`saved_to`)
- Preview of top 3–5 matches: name, research focus, why it fits
- Note if any professors had inaccessible homepages

## Context Management

- Tool results > 8000 chars are automatically spilled to disk with a preview + file path. Use `read_file(path)` to access the full content.
- If context grows large during the research loop, call `compact_context(focus="professor research summaries and user interests")` before starting the next batch.
- You don't need to research every professor — 10–20 high-quality summaries is enough for a good report.

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
| Homepage fetch fails | Try `https://scholar.google.com/citations?user=<scholarid>` |
| PDF extraction returns empty | Page may be image-only scan — skip or note in summary |
| Context growing too large | Call `compact_context` before next professor batch |
| generate_match_report fails with provider error | Check `.env` for ANTHROPIC_API_KEY / OPENAI_API_KEY |
