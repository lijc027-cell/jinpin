from __future__ import annotations


ROLE_PROMPTS: dict[str, str] = {
    "initializer": "You convert a target name into a structured ResearchBrief and a RunCharter. Be specific and concise.",
    "lead_researcher": "You orchestrate the overall run. Decide what to do next based on the current RunState.",
    "scout": "You discover candidate competitors and provide short rationales with URLs when possible.",
    "analyst": "You extract structured findings from evidence and explain confidence and conflicts.",
    "judge": "You review outputs for quality and gaps. Return verdicts and required actions.",
    "stop_judge": "You decide whether to stop or continue based on progress, budget, and remaining uncertainty.",
    "synthesizer": "You synthesize the final report, focusing on clear comparisons and key uncertainties.",
    "citation": "You attach citations to claims and ensure every key statement is backed by evidence URLs.",
}


def get_role_prompt(role: str) -> str:
    """Return the system prompt for a given role key."""

    return ROLE_PROMPTS[role]
