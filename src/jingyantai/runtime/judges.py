from __future__ import annotations

from jingyantai.domain.models import GapTicket, ReviewDecision, RunState, StopDecision
from jingyantai.domain.phases import CandidateStatus, GapPriority, ReviewVerdict, StopVerdict


def _covered_dimensions_for_candidate(
    state: RunState, *, candidate_id: str, required_dimensions: list[str]
) -> set[str]:
    evidence_ids = {evidence.evidence_id for evidence in state.evidence}

    covered: set[str] = set()
    for finding in state.findings:
        if finding.subject_id != candidate_id:
            continue
        if finding.dimension not in required_dimensions:
            continue
        if not finding.evidence_ids:
            continue
        if all(evidence_id in evidence_ids for evidence_id in finding.evidence_ids):
            covered.add(finding.dimension)
    return covered


class EvidenceJudge:
    def run(self, state: RunState) -> ReviewDecision:
        # Minimal contract implementation; richer logic is intentionally deferred.
        if not state.evidence:
            return ReviewDecision(
                judge_type="evidence_judge",
                target_scope="run",
                verdict=ReviewVerdict.WARN,
                reasons=["No evidence collected yet."],
                required_actions=["Collect primary-source evidence for key claims."],
            )
        return ReviewDecision(
            judge_type="evidence_judge",
            target_scope="run",
            verdict=ReviewVerdict.PASS,
            reasons=["Evidence present."],
            required_actions=[],
        )


class CoverageJudge:
    def __init__(self, required_dimensions: list[str]) -> None:
        self.required_dimensions = list(required_dimensions)

    def run(self, state: RunState) -> ReviewDecision:
        if not self.required_dimensions:
            return ReviewDecision(
                judge_type="coverage_judge",
                target_scope="run",
                verdict=ReviewVerdict.WARN,
                reasons=["No required_dimensions configured for CoverageJudge."],
            )

        confirmed = [candidate for candidate in state.candidates if candidate.status == CandidateStatus.CONFIRMED]
        if not confirmed:
            return ReviewDecision(
                judge_type="coverage_judge",
                target_scope="run",
                verdict=ReviewVerdict.WARN,
                reasons=["No confirmed candidates to evaluate coverage for."],
            )

        missing_by_candidate: dict[str, list[str]] = {}
        for candidate in confirmed:
            covered = _covered_dimensions_for_candidate(
                state, candidate_id=candidate.candidate_id, required_dimensions=self.required_dimensions
            )
            missing = [dimension for dimension in self.required_dimensions if dimension not in covered]
            if missing:
                missing_by_candidate[candidate.candidate_id] = missing

        if missing_by_candidate:
            reasons = [
                f"Candidate {candidate_id} missing: {', '.join(missing)}"
                for candidate_id, missing in sorted(missing_by_candidate.items())
            ]
            return ReviewDecision(
                judge_type="coverage_judge",
                target_scope="run",
                verdict=ReviewVerdict.FAIL,
                reasons=reasons,
                required_actions=["Fill missing required dimensions for confirmed candidates."],
            )

        return ReviewDecision(
            judge_type="coverage_judge",
            target_scope="run",
            verdict=ReviewVerdict.PASS,
            reasons=["All required dimensions covered for confirmed candidates."],
            required_actions=[],
        )


class Challenger:
    def run(self, state: RunState) -> ReviewDecision:
        confirmed = [candidate for candidate in state.candidates if candidate.status == CandidateStatus.CONFIRMED]
        if not confirmed:
            return ReviewDecision(
                judge_type="challenger",
                target_scope="run",
                verdict=ReviewVerdict.WARN,
                reasons=[
                    "No confirmed candidates yet.",
                    "Consider alternative discovery angles and disconfirming evidence sources.",
                ],
                required_actions=["Expand candidate discovery and collect independent primary sources."],
            )
        return ReviewDecision(
            judge_type="challenger",
            target_scope="run",
            verdict=ReviewVerdict.PASS,
            reasons=["Challenge checks passed: confirmed candidates exist."],
            required_actions=["Seek at least one independent primary source per dimension for each confirmed candidate."],
        )


class StopJudge:
    def __init__(self, required_dimensions: list[str]) -> None:
        self.required_dimensions = list(required_dimensions)

    def run(self, state: RunState) -> StopDecision:
        confirmed = [candidate for candidate in state.candidates if candidate.status == CandidateStatus.CONFIRMED]
        if not self.required_dimensions:
            return StopDecision(
                verdict=StopVerdict.CONTINUE,
                reasons=["No required_dimensions configured for StopJudge; continue."],
                gap_tickets=[],
            )

        gap_tickets: list[GapTicket] = []
        for candidate in confirmed:
            covered = _covered_dimensions_for_candidate(
                state, candidate_id=candidate.candidate_id, required_dimensions=self.required_dimensions
            )
            missing = [dimension for dimension in self.required_dimensions if dimension not in covered]
            if not missing:
                continue
            gap_tickets.append(
                GapTicket(
                    gap_type="missing_required_dimensions",
                    target_scope=candidate.candidate_id,
                    blocking_reason=(
                        "Missing evidence-backed findings for required dimensions: "
                        f"{', '.join(missing)}."
                    ),
                    owner_role="analyst",
                    acceptance_rule="Add findings backed by evidence for each missing required dimension.",
                    deadline_round=state.round_index + 1,
                    priority=GapPriority.HIGH,
                    retry_count=0,
                )
            )

        if gap_tickets:
            return StopDecision(
                verdict=StopVerdict.CONTINUE,
                reasons=["Coverage gaps remain for confirmed candidates."],
                gap_tickets=gap_tickets,
            )

        if not confirmed:
            return StopDecision(
                verdict=StopVerdict.CONTINUE,
                reasons=["No confirmed candidates yet."],
                gap_tickets=[],
            )

        if self.required_dimensions:
            return StopDecision(
                verdict=StopVerdict.STOP,
                reasons=["All required dimensions covered for confirmed candidates."],
                gap_tickets=[],
            )

        return StopDecision(
            verdict=StopVerdict.CONTINUE,
            reasons=["Missing required dimensions definition; continue."],
            gap_tickets=[],
        )
