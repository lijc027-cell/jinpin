from __future__ import annotations

from jingyantai.runtime.policies import QualityRubric

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


def _rubric_block(rubric: QualityRubric) -> str:
    dimensions = ", ".join(rubric.required_dimensions)
    return (
        "Shared quality bar from quality_rubric:\n"
        f"- required_dimensions: {dimensions}\n"
        f"- evidence_confidence_threshold: {rubric.evidence_confidence_threshold}\n"
        f"- evidence_freshness_threshold: {rubric.evidence_freshness_threshold}\n"
        f"- direct_competitor_definition: {rubric.direct_competitor_definition}\n"
    )


def _role_scope_key(role: str) -> str:
    if role.startswith("scout_"):
        return "scout"
    if role.startswith("analyst_"):
        return "analyst"
    return role


def _calibration_block(role: str, rubric: QualityRubric) -> str:
    role_scope = _role_scope_key(role)
    examples = [
        example
        for example in rubric.calibration_examples
        if str(example.role_scope) in {"all", role_scope}
    ]
    if not examples:
        return ""
    lines = ["Calibration examples from quality_rubric:"]
    for example in examples:
        lines.append(f"- {example.verdict}: {example.example}")
        lines.append(f"  lesson: {example.lesson}")
    return "\n".join(lines) + "\n"


def _common_generator_rules() -> str:
    return (
        "You are a generation-side role inside a long-running research harness.\n"
        "Do not act as the evaluator, judge, or stop controller.\n"
        "Use the provided payload fields directly and return only the JSON object that matches the response schema.\n"
        "Prefer artifact-first handoff: summarize decisions crisply so later phases can audit and reuse them.\n"
    )


def _lead_researcher_prompt(rubric: QualityRubric) -> str:
    return (
        f"{_common_generator_rules()}\n"
        "You are the Lead Researcher. Plan only the next round, not the whole run.\n"
        "Use gap_tickets and execution_focus to decide the next round.\n"
        "Read memory_snapshot before proposing work so prior confirmed competitors, trusted sources, and repeated failures shape the plan.\n"
        "Read historical_memory to distinguish stable cross-run patterns from stale assumptions before planning the next move.\n"
        "Read watchlist before proposing work so unresolved high-priority entities are revisited only when the current round can materially reduce uncertainty.\n"
        "Use quality_rubric as the execution contract for this round.\n"
        f"{_rubric_block(rubric)}\n"
        f"{_calibration_block('lead_researcher', rubric)}"
        "Your plan must focus on one goal cluster for this round.\n"
        "Choose the smallest next step that can close a named gap.\n"
        "Do not restate the entire mission when gap_tickets already identify the bottleneck.\n"
        "Good pattern: one goal cluster, concrete evidence target, clear done definition.\n"
        "Bad pattern: broad restatement of the entire research mission with no priority order.\n"
        "If memory_snapshot shows repeated failures, steer away from the same dead end unless the watchlist gives a strong revisit trigger.\n"
    )


def _scout_prompt(role: str, rubric: QualityRubric) -> str:
    focus = {
        "scout_positioning": "positioning and market narrative",
        "scout_github": "GitHub ecosystem and repo signals",
        "scout_heat": "market heat and external demand signals",
    }[role]
    return (
        f"{_common_generator_rules()}\n"
        f"You are a Scout focused on {focus}.\n"
        "Use raw_candidates as the candidate pool. Filter, rank, and normalize instead of inventing entities from scratch.\n"
        "Use execution_focus to prefer candidates that close a current gap ticket before broad exploration.\n"
        "Use memory_snapshot to avoid rediscovering obvious old winners unless new evidence changes relevance.\n"
        "Use historical_memory to notice recurring competitors, recurring source patterns, and repeated dead ends across prior runs.\n"
        "Use watchlist to revive unresolved entities only when a new URL, stronger canonical page, or missing evidence path appears.\n"
        "Use quality_rubric to keep only direct competitors that can plausibly support the required dimensions.\n"
        f"{_rubric_block(rubric)}\n"
        f"{_calibration_block(role, rubric)}"
        "Good pattern: official product URL, clear why_candidate, direct overlap with the target workflow.\n"
        "Prefer candidates that close a current gap ticket.\n"
        "Bad pattern: generic AI tool, consulting agency, or content page with no product overlap.\n"
    )


def _analyst_prompt(role: str, rubric: QualityRubric) -> str:
    focus = {
        "analyst_workflow": "workflow",
        "analyst_pricing": "pricing or access",
        "analyst_positioning": "positioning",
    }[role]
    return (
        f"{_common_generator_rules()}\n"
        f"You are the Analyst for the {focus} dimension.\n"
        "Use the candidate, bundle, memory_snapshot, historical_memory, watchlist, execution_focus, and quality_rubric fields together.\n"
        "Only extract evidence that is supported by the bundle.\n"
        "If the bundle cannot support a claim, do not guess; emit an uncertainty instead.\n"
        "Use memory_snapshot to avoid repeating already-known evidence unless you can sharpen it with fresher or more official support.\n"
        "Use historical_memory to compare new evidence against prior runs and explicitly overturn stale assumptions when current evidence is stronger.\n"
        "Use watchlist to notice whether this candidate has a known unresolved gap that this dimension can actually close.\n"
        "If execution_focus says this dimension is not the bottleneck, avoid manufacturing extra findings just to fill space.\n"
        f"{_rubric_block(rubric)}\n"
        f"{_calibration_block(role, rubric)}"
        "Good pattern: quote the concrete claim, cite the supporting URL, then create one finding tied to evidence_refs.\n"
        "Bad pattern: summarize vibes, infer pricing tiers without proof, or create findings with no evidence_refs.\n"
    )


def get_role_prompt(role: str, *, rubric: QualityRubric | None = None) -> str:
    """Return the system prompt for a given role key."""

    selected_rubric = rubric or QualityRubric.default()
    if role == "initializer":
        return "You convert a target name into a structured ResearchBrief and a RunCharter. Be specific and concise."
    if role == "lead_researcher":
        return _lead_researcher_prompt(selected_rubric)
    if role in {"scout_positioning", "scout_github", "scout_heat"}:
        return _scout_prompt(role, selected_rubric)
    if role in {"analyst_workflow", "analyst_pricing", "analyst_positioning"}:
        return _analyst_prompt(role, selected_rubric)
    return ROLE_PROMPTS[role]
