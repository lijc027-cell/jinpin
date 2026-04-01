from __future__ import annotations

from pydantic import BaseModel, Field

from jingyantai.domain.phases import (
    CandidateStatus,
    GapPriority,
    HypothesisStatus,
    Phase,
    ReviewVerdict,
    StopVerdict,
)


class BudgetPolicy(BaseModel):
    max_rounds: int
    max_active_candidates: int
    max_deepen_targets: int
    max_external_fetches: int
    max_run_duration_minutes: int


class ResearchBrief(BaseModel):
    target: str
    product_type: str
    competitor_definition: str
    required_dimensions: list[str]
    stop_policy: str
    budget: BudgetPolicy


class RunCharter(BaseModel):
    mission: str
    scope: list[str]
    non_goals: list[str]
    success_criteria: list[str]
    research_agenda: list[str]


class Hypothesis(BaseModel):
    statement: str
    status: HypothesisStatus = HypothesisStatus.UNTESTED
    related_candidates: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    conflicting_evidence_ids: list[str] = Field(default_factory=list)


class Candidate(BaseModel):
    candidate_id: str
    name: str
    canonical_url: str
    status: CandidateStatus
    relevance_score: float
    why_candidate: str
    aliases: list[str] = Field(default_factory=list)
    company: str | None = None
    why_not_candidate: str | None = None

    def transition_to(self, new_status: CandidateStatus) -> None:
        valid_transitions = {
            CandidateStatus.DISCOVERED: {CandidateStatus.NORMALIZED, CandidateStatus.REJECTED},
            CandidateStatus.NORMALIZED: {CandidateStatus.PLAUSIBLE, CandidateStatus.REJECTED},
            CandidateStatus.PLAUSIBLE: {CandidateStatus.PRIORITIZED, CandidateStatus.REJECTED},
            CandidateStatus.PRIORITIZED: {CandidateStatus.CONFIRMED, CandidateStatus.REJECTED},
            CandidateStatus.CONFIRMED: set(),
            CandidateStatus.REJECTED: set(),
        }
        if new_status not in valid_transitions[self.status]:
            raise ValueError(f"Invalid status transition: {self.status} -> {new_status}")
        self.status = new_status


class Evidence(BaseModel):
    evidence_id: str
    subject_id: str
    claim: str
    source_url: str
    source_type: str
    snippet: str
    captured_at: str
    freshness_score: float
    confidence: float
    supports_or_conflicts: str = "supports"


class Finding(BaseModel):
    finding_id: str
    subject_id: str
    dimension: str
    summary: str
    evidence_ids: list[str]
    confidence: float
    conflict_flags: list[str] = Field(default_factory=list)


class OpenQuestion(BaseModel):
    question: str
    target_subject: str
    priority: GapPriority
    owner_role: str
    created_by: str


class UncertaintyItem(BaseModel):
    statement: str
    impact: str
    resolvability: str
    required_evidence: str
    owner_role: str


class GapTicket(BaseModel):
    gap_type: str
    target_scope: str
    blocking_reason: str
    owner_role: str
    acceptance_rule: str
    deadline_round: int
    priority: GapPriority
    retry_count: int = 0


class ReviewDecision(BaseModel):
    judge_type: str
    target_scope: str
    verdict: ReviewVerdict
    reasons: list[str]
    required_actions: list[str] = Field(default_factory=list)


class StopDecision(BaseModel):
    verdict: StopVerdict
    reasons: list[str]
    gap_tickets: list[GapTicket] = Field(default_factory=list)


class RunTrace(BaseModel):
    round_index: int
    phase: Phase
    planner_output: str
    dispatched_tasks: list[str]
    new_candidates: list[str]
    new_findings: list[str]
    review_decisions: list[str]
    stop_or_continue: str


class FinalReport(BaseModel):
    target_summary: str
    confirmed_competitors: list[str]
    rejected_candidates: list[str]
    comparison_matrix: list[dict[str, str]]
    key_uncertainties: list[str]
    citations: dict[str, list[str]]


class RunState(BaseModel):
    run_id: str
    target: str
    current_phase: Phase
    budget: BudgetPolicy
    brief: ResearchBrief | None = None
    charter: RunCharter | None = None
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    candidates: list[Candidate] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    uncertainties: list[UncertaintyItem] = Field(default_factory=list)
    gap_tickets: list[GapTicket] = Field(default_factory=list)
    review_decisions: list[ReviewDecision] = Field(default_factory=list)
    traces: list[RunTrace] = Field(default_factory=list)
    final_report: FinalReport | None = None
    round_index: int = 0
    external_fetch_count: int = 0
    carry_forward_context: str = ""

    def top_candidates(self, limit: int) -> list[Candidate]:
        prioritized = [
            candidate
            for candidate in self.candidates
            if candidate.status in {CandidateStatus.PRIORITIZED, CandidateStatus.CONFIRMED}
        ]
        return sorted(prioritized, key=lambda candidate: candidate.relevance_score, reverse=True)[:limit]
