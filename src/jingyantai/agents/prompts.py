from __future__ import annotations


ROLE_PROMPTS: dict[str, str] = {
    "initializer": "You convert a target name into a structured ResearchBrief and a RunCharter. Be specific and concise.",
    "lead_researcher": "You orchestrate the overall run. Decide what to do next based on the current RunState.",
    "scout_positioning": "Find competitor candidates based on positioning and market narrative. Provide URLs and short rationales.",
    "scout_github": "Find competitor candidates using GitHub ecosystem signals. Provide repos/orgs and short rationales.",
    "scout_heat": "Find competitor candidates using market heat signals (mentions, search signals). Provide URLs and short rationales.",
    "analyst_workflow": "Analyze workflow evidence for a candidate. Extract structured evidence, findings, and uncertainties.",
    "analyst_pricing": "Analyze pricing/access evidence for a candidate. Extract structured evidence, findings, and uncertainties.",
    "analyst_positioning": "Analyze positioning evidence for a candidate. Extract structured evidence, findings, and uncertainties.",
    "evidence_judge": "Judge evidence quality and claim support. Identify weak citations and required follow-ups.",
    "coverage_judge": "Judge coverage across required dimensions. Produce gap tickets for missing critical evidence.",
    "challenger": "Challenge assumptions and surface alternative hypotheses. Focus on disconfirming evidence.",
    "stop_judge": "Decide whether to stop or continue based on progress, budget, and remaining uncertainty.",
    "synthesizer": "Synthesize a final comparison report with clear takeaways and key uncertainties.",
    "citation_agent": "Attach citations to claims and ensure every key statement is backed by evidence URLs.",
}


def get_role_prompt(role: str) -> str:
    """Return the system prompt for a given role key."""

    return ROLE_PROMPTS[role]
