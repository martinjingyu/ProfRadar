"""
Final matching step: take all professor short summaries + user interests,
ask LLM for ranked recommendations with personalized cold-email tips.
"""

from providers.base import LLMProvider

_SYSTEM = """You are an expert academic advisor helping PhD applicants find the best professors to cold-email.
You will receive:
1. A list of professors with their short research summaries
2. The student's research interests and any additional requirements

Your job: select the TOP 8 professors (or fewer if less are relevant), rank them by fit,
and for each explain WHY they match and give a concrete cold-email tip.

Write your response in English. Be specific — cite actual research directions from the summaries, not generic advice."""

_PROMPT_TMPL = """\
## Student Interests

{user_profile}

---

## Professor List ({total} professors with short summaries)

{professor_list}

---

## Task

From the {total} professors above, select the **top 8** best matches (ranked by fit).

For each recommended professor, provide:
1. **Why it fits**: specific overlap between their research and the student's interests
2. **Email tip**: one concrete sentence — what to mention in the cold email (specific paper, project, or shared direction)

Format:
### 1. Professor Name
**Research focus**: ...
**Why it fits**: ...
**Email tip**: ...

---
"""


def _build_professor_list(summaries: list[dict]) -> str:
    lines = []
    for i, s in enumerate(summaries, 1):
        areas = ", ".join(s["areas"][:4]) if s["areas"] else "Unknown"
        lines.append(
            f"{i}. **{s['name']}** ({areas})\n"
            f"   {s['short_summary']}"
        )
    return "\n\n".join(lines)


def match_professors(
    summaries: list[dict],
    user_profile: str,
    provider: LLMProvider,
) -> str:
    """
    Returns the LLM's ranked recommendation as a Markdown string.

    summaries:    output of professor_pipeline.run_pipeline()
    user_profile: student's research interests and requirements
    """
    professor_list = _build_professor_list(summaries)

    prompt = _PROMPT_TMPL.format(
        user_profile=user_profile,
        total=len(summaries),
        professor_list=professor_list,
    )

    print(f"\nMatching {len(summaries)} professors to your interests...\n")

    return provider.generate(
        system=_SYSTEM,
        prompt=prompt,
        max_tokens=4096,
    )
