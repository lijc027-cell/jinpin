from __future__ import annotations

from jingyantai.domain.models import GapTicket, ReviewDecision, RunState, StopDecision
from jingyantai.domain.phases import CandidateStatus, GapPriority, ReviewVerdict, StopVerdict


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
    def run(self, state: RunState) -> ReviewDecision:
        required = state.brief.required_dimensions if state.brief else []
        if not required:
            return ReviewDecision(
                judge_type="coverage_judge",
                target_scope="run",
                verdict=ReviewVerdict.WARN,
                reasons=["No required dimensions available in brief."],
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
            covered = {
                finding.dimension
                for finding in state.findings
                if finding.subject_id == candidate.candidate_id and finding.dimension in required
            }
            missing = [dimension for dimension in required if dimension not in covered]
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
    def run(self, state: RunState) -> str:
        # Minimal challenger output; callers can log or feed into planning.
        confirmed = [candidate for candidate in state.candidates if candidate.status == CandidateStatus.CONFIRMED]
        if not confirmed:
            return "Challenge: no confirmed candidates yet; consider alternate sources and candidate discovery angles."
        return "Challenge: verify each confirmed candidate with at least one independent primary source per dimension."


class StopJudge:
    def run(self, state: RunState) -> StopDecision:
        required = state.brief.required_dimensions if state.brief else []
        confirmed = [candidate for candidate in state.candidates if candidate.status == CandidateStatus.CONFIRMED]

        gap_tickets: list[GapTicket] = []
        for candidate in confirmed:
            covered = {
                finding.dimension
                for finding in state.findings
                if finding.subject_id == candidate.candidate_id and finding.dimension in required
            }
            missing = [dimension for dimension in required if dimension not in covered]
            if not missing:
                continue
            gap_tickets.append(
                GapTicket(
                    gap_type="missing_required_dimensions",
                    target_scope=candidate.candidate_id,
                    blocking_reason=f"Missing findings for required dimensions: {', '.join(missing)}.",
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

        if required:
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
