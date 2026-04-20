from __future__ import annotations

from jingyantai.domain.models import GapTicket, ReviewDecision, RunState, StopDecision
from jingyantai.domain.phases import CandidateStatus, GapPriority, ReviewVerdict, StopVerdict
from jingyantai.runtime.policies import QualityRubric, StopBar


def _is_acceptable_support_evidence(
    *,
    candidate_id: str,
    evidence: object,
    confidence_threshold: float,
    freshness_threshold: float,
) -> bool:
    # Keep this tiny and explicit; tests lock the semantics.
    if getattr(evidence, "subject_id", None) != candidate_id:
        return False
    if getattr(evidence, "supports_or_conflicts", "supports") != "supports":
        return False
    if getattr(evidence, "confidence", 0.0) < confidence_threshold:
        return False
    if getattr(evidence, "freshness_score", 0.0) < freshness_threshold:
        return False
    return True


def _covered_dimensions_for_candidate(
    state: RunState,
    *,
    candidate_id: str,
    required_dimensions: list[str],
    rubric: QualityRubric,
) -> set[str]:
    evidence_by_id = {evidence.evidence_id: evidence for evidence in state.evidence}

    covered: set[str] = set()
    for finding in state.findings:
        if finding.subject_id != candidate_id:
            continue
        if finding.dimension not in required_dimensions:
            continue
        if not finding.evidence_ids:
            continue
        if all(
            evidence_id in evidence_by_id
            and _is_acceptable_support_evidence(
                candidate_id=candidate_id,
                evidence=evidence_by_id[evidence_id],
                confidence_threshold=rubric.evidence_confidence_threshold,
                freshness_threshold=rubric.evidence_freshness_threshold,
            )
            for evidence_id in finding.evidence_ids
        ):
            covered.add(finding.dimension)
    return covered


def _normalized_text(value: str) -> str:
    return value.strip().lower()


class EvidenceJudge:
    def __init__(self, rubric: QualityRubric | None = None) -> None:
        self.rubric = rubric or QualityRubric.default()

    def run(self, state: RunState) -> ReviewDecision:
        conflicts = [evidence for evidence in state.evidence if evidence.supports_or_conflicts != "supports"]
        stale = [
            evidence
            for evidence in state.evidence
            if evidence.freshness_score < self.rubric.evidence_freshness_threshold
        ]
        weak = [
            evidence
            for evidence in state.evidence
            if evidence.confidence < self.rubric.evidence_confidence_threshold
        ]

        if conflicts or stale or weak:
            pieces: list[str] = []
            if conflicts:
                pieces.append(
                    "conflict evidence: " + ", ".join(evidence.evidence_id for evidence in conflicts)
                )
            if stale:
                pieces.append(
                    "stale evidence: " + ", ".join(evidence.evidence_id for evidence in stale)
                )
            if weak:
                weak_labels = [f"{evidence.evidence_id}({evidence.confidence:.2f})" for evidence in weak]
                pieces.append("low-confidence evidence: " + ", ".join(weak_labels))
            return ReviewDecision(
                judge_type="evidence",
                target_scope="run",
                verdict=ReviewVerdict.FAIL,
                reasons=["Evidence quality gate failed: " + "; ".join(pieces) + "."],
                required_actions=[
                    "Replace, corroborate, or remove non-supporting / stale / low-confidence evidence IDs: "
                    + ", ".join({evidence.evidence_id for evidence in conflicts + stale + weak})
                    + "."
                ],
            )

        return ReviewDecision(
            judge_type="evidence",
            target_scope="run",
            verdict=ReviewVerdict.PASS,
            reasons=["Evidence quality gate passed."],
            required_actions=[],
        )


class CoverageJudge:
    def __init__(
        self,
        required_dimensions: list[str] | None = None,
        rubric: QualityRubric | None = None,
    ) -> None:
        self.rubric = rubric or QualityRubric.default()
        self.required_dimensions = (
            list(required_dimensions) if required_dimensions is not None else list(self.rubric.required_dimensions)
        )

    def run(self, state: RunState) -> ReviewDecision:
        if not self.required_dimensions:
            return ReviewDecision(
                judge_type="coverage",
                target_scope="confirmed_candidates",
                verdict=ReviewVerdict.WARN,
                reasons=["No required_dimensions configured for CoverageJudge."],
            )

        confirmed = [candidate for candidate in state.candidates if candidate.status == CandidateStatus.CONFIRMED]
        if not confirmed:
            return ReviewDecision(
                judge_type="coverage",
                target_scope="confirmed_candidates",
                verdict=ReviewVerdict.WARN,
                reasons=["No confirmed candidates to evaluate coverage for."],
            )

        missing_by_candidate: dict[str, list[str]] = {}
        for candidate in confirmed:
            covered = _covered_dimensions_for_candidate(
                state,
                candidate_id=candidate.candidate_id,
                required_dimensions=self.required_dimensions,
                rubric=self.rubric,
            )
            missing = [dimension for dimension in self.required_dimensions if dimension not in covered]
            if missing:
                missing_by_candidate[candidate.candidate_id] = missing

        if missing_by_candidate:
            reasons: list[str] = []
            required_actions: list[str] = []
            for candidate in confirmed:
                missing = missing_by_candidate.get(candidate.candidate_id)
                if not missing:
                    continue
                reasons.append(f"{candidate.name} missing: {', '.join(missing)}")
                required_actions.extend([f"{candidate.name}: {dimension}" for dimension in missing])
            return ReviewDecision(
                judge_type="coverage",
                target_scope="confirmed_candidates",
                verdict=ReviewVerdict.FAIL,
                reasons=reasons,
                required_actions=required_actions,
            )

        return ReviewDecision(
            judge_type="coverage",
            target_scope="confirmed_candidates",
            verdict=ReviewVerdict.PASS,
            reasons=["All required dimensions covered for confirmed candidates."],
            required_actions=[],
        )


class Challenger:
    def run(self, state: RunState) -> ReviewDecision:
        scoped = [
            candidate
            for candidate in state.candidates
            if candidate.status in {CandidateStatus.PRIORITIZED, CandidateStatus.CONFIRMED}
        ]
        if not scoped:
            return ReviewDecision(
                judge_type="challenger",
                target_scope="candidate_fit",
                verdict=ReviewVerdict.WARN,
                reasons=[
                    "No prioritized/confirmed candidates to challenge yet.",
                    "Consider alternative discovery angles.",
                ],
                required_actions=["Expand candidate discovery and validate direct-competitor fit."],
            )

        platform_named = [c for c in scoped if "platform" in c.why_candidate.lower()]
        if platform_named:
            return ReviewDecision(
                judge_type="challenger",
                target_scope="candidate_fit",
                verdict=ReviewVerdict.WARN,
                reasons=[
                    "Some candidates are described as a platform; confirm they are direct competitors.",
                    "Platform-language can indicate a broader product scope than a terminal-native coding agent.",
                ],
                required_actions=[f"Verify direct competitor fit for: {', '.join(c.name for c in platform_named)}."],
            )

        return ReviewDecision(
            judge_type="challenger",
            target_scope="candidate_fit",
            verdict=ReviewVerdict.PASS,
            reasons=["No platform-language found in why_candidate for prioritized/confirmed candidates."],
            required_actions=[],
        )


class StopJudge:
    def __init__(
        self,
        required_dimensions: list[str] | None = None,
        stop_bar: StopBar | None = None,
        rubric: QualityRubric | None = None,
    ) -> None:
        self.rubric = rubric or QualityRubric.default()
        self.required_dimensions = (
            list(required_dimensions) if required_dimensions is not None else list(self.rubric.required_dimensions)
        )
        self.stop_bar = stop_bar or StopBar.default()

    def _coverage_ratio(self, state: RunState, confirmed: list[object]) -> float:
        if not confirmed or not self.required_dimensions:
            return 0.0

        fully_covered = 0
        for candidate in confirmed:
            covered = _covered_dimensions_for_candidate(
                state,
                candidate_id=getattr(candidate, "candidate_id", ""),
                required_dimensions=self.required_dimensions,
                rubric=self.rubric,
            )
            if len(covered) == len(self.required_dimensions):
                fully_covered += 1
        return fully_covered / len(confirmed)

    def _is_high_impact_uncertainty(self, uncertainty: object) -> bool:
        impact = _normalized_text(str(getattr(uncertainty, "impact", "")))
        stop_impacts = {_normalized_text(item) for item in self.rubric.high_impact_uncertainty_impacts}
        return impact in stop_impacts

    def _uncertainty_target_scope(self, state: RunState, uncertainty: object) -> str:
        statement = _normalized_text(str(getattr(uncertainty, "statement", "")))
        confirmed = [candidate for candidate in state.candidates if candidate.status == CandidateStatus.CONFIRMED]
        for candidate in sorted(confirmed, key=lambda item: len(item.name), reverse=True):
            name = _normalized_text(candidate.name)
            if name and name in statement:
                return candidate.name
            candidate_id = _normalized_text(candidate.candidate_id)
            if candidate_id and candidate_id in statement:
                return candidate.name
            for alias in getattr(candidate, "aliases", []):
                normalized_alias = _normalized_text(str(alias))
                if normalized_alias and normalized_alias in statement:
                    return candidate.name
        return "run"

    def run(self, state: RunState) -> StopDecision:
        confirmed = [candidate for candidate in state.candidates if candidate.status == CandidateStatus.CONFIRMED]
        if len(confirmed) < self.stop_bar.min_confirmed_candidates:
            return StopDecision(
                verdict=StopVerdict.CONTINUE,
                reasons=["Hard gate failed: not enough confirmed competitors."],
                gap_tickets=[],
            )

        if not self.required_dimensions:
            return StopDecision(
                verdict=StopVerdict.CONTINUE,
                reasons=["Quality bar not met"],
                gap_tickets=[],
            )

        reasons = ["Quality bar not met"]
        gap_tickets: list[GapTicket] = []

        unresolved_review = [
            decision
            for decision in state.review_decisions
            if decision.verdict in {ReviewVerdict.FAIL, ReviewVerdict.WARN}
        ]
        if unresolved_review:
            gap_tickets.append(
                GapTicket(
                    gap_type="review_decisions",
                    target_scope="run",
                    blocking_reason="Unresolved review decisions exist.",
                    owner_role="lead_researcher",
                    acceptance_rule="Resolve all FAIL/WARN review decisions.",
                    deadline_round=state.round_index + 1,
                    priority=GapPriority.HIGH,
                    retry_count=0,
                )
            )

        if state.open_questions:
            for question in state.open_questions:
                target_scope = getattr(question, "target_subject", "") or "run"
                gap_tickets.append(
                    GapTicket(
                        gap_type="open_questions",
                        target_scope=target_scope,
                        blocking_reason=str(getattr(question, "question", "Open question remains.")),
                        owner_role=str(getattr(question, "owner_role", "analyst")),
                        acceptance_rule="Answer this open question with direct evidence.",
                        deadline_round=state.round_index + 1,
                        priority=getattr(question, "priority", GapPriority.MEDIUM),
                        retry_count=0,
                    )
                )

        high_impact_uncertainties = 0
        if state.uncertainties:
            for uncertainty in state.uncertainties:
                is_high_impact = self._is_high_impact_uncertainty(uncertainty)
                if is_high_impact:
                    high_impact_uncertainties += 1
                required_evidence = str(getattr(uncertainty, "required_evidence", "")).strip()
                acceptance_rule = "Resolve or explicitly bound this uncertainty with direct evidence."
                if required_evidence:
                    acceptance_rule = (
                        "Resolve or explicitly bound this uncertainty with direct evidence, ideally "
                        f"{required_evidence}."
                    )
                gap_tickets.append(
                    GapTicket(
                        gap_type="uncertainties",
                        target_scope=self._uncertainty_target_scope(state, uncertainty),
                        blocking_reason=str(getattr(uncertainty, "statement", "Uncertainty remains.")),
                        owner_role=str(getattr(uncertainty, "owner_role", "analyst")),
                        acceptance_rule=acceptance_rule,
                        deadline_round=state.round_index + 1,
                        priority=GapPriority.HIGH if is_high_impact else GapPriority.MEDIUM,
                        retry_count=0,
                    )
                )

        for candidate in confirmed:
            covered = _covered_dimensions_for_candidate(
                state,
                candidate_id=candidate.candidate_id,
                required_dimensions=self.required_dimensions,
                rubric=self.rubric,
            )
            missing = [dimension for dimension in self.required_dimensions if dimension not in covered]
            if not missing:
                continue
            gap_tickets.append(
                GapTicket(
                    gap_type="coverage",
                    target_scope=candidate.name,
                    blocking_reason=(
                        "Missing dimensions: "
                        f"{', '.join(missing)}"
                    ),
                    owner_role="analyst",
                    acceptance_rule="Cover all required dimensions with direct evidence.",
                    deadline_round=state.round_index + 1,
                    priority=GapPriority.HIGH,
                    retry_count=0,
                )
            )

        coverage_ratio = self._coverage_ratio(state, confirmed)
        if coverage_ratio < self.stop_bar.min_coverage_ratio:
            reasons.append(
                "Coverage ratio "
                f"{coverage_ratio:.2f} below stop bar {self.stop_bar.min_coverage_ratio:.2f}."
            )

        if high_impact_uncertainties > self.stop_bar.max_high_impact_uncertainties:
            reasons.append(
                "High-impact uncertainties exceed stop bar: "
                f"{high_impact_uncertainties} > {self.stop_bar.max_high_impact_uncertainties}."
            )

        if gap_tickets:
            return StopDecision(
                verdict=StopVerdict.CONTINUE,
                reasons=reasons,
                gap_tickets=gap_tickets,
            )

        return StopDecision(
            verdict=StopVerdict.STOP,
            reasons=["Quality bar met"],
            gap_tickets=[],
        )
