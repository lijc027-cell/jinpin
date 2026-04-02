from __future__ import annotations

from jingyantai.domain.models import FinalReport, RunState
from jingyantai.domain.phases import CandidateStatus


class Synthesizer:
    def run(self, state: RunState) -> FinalReport:
        confirmed = [candidate for candidate in state.candidates if candidate.status == CandidateStatus.CONFIRMED]
        rejected = [candidate for candidate in state.candidates if candidate.status == CandidateStatus.REJECTED]
        return FinalReport(
            target_summary=f"Competitive landscape for {state.target}",
            confirmed_competitors=[candidate.name for candidate in confirmed],
            rejected_candidates=[candidate.name for candidate in rejected],
            comparison_matrix=[
                {"candidate": candidate.name, "url": candidate.canonical_url}
                for candidate in confirmed
            ],
            key_uncertainties=[item.statement for item in state.uncertainties],
            citations={},
        )


class CitationAgent:
    def run(self, state: RunState, draft: FinalReport) -> FinalReport:
        citations: dict[str, list[str]] = {}
        for candidate in state.candidates:
            citations[candidate.name] = sorted(
                {
                    evidence.source_url
                    for evidence in state.evidence
                    if evidence.subject_id == candidate.candidate_id
                }
            )
        return draft.model_copy(update={"citations": citations})
