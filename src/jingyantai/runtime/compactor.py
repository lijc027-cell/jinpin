from __future__ import annotations

from jingyantai.domain.models import RunState
from jingyantai.domain.phases import CandidateStatus


class ContextCompactor:
    def compact(self, state: RunState) -> str:
        """Produce a carry-forward snapshot string for the next round/phase."""

        top_candidates = state.top_candidates(limit=5)
        confirmed = [candidate for candidate in state.candidates if candidate.status == CandidateStatus.CONFIRMED]

        lines: list[str] = []
        lines.append("CARRY-FORWARD SNAPSHOT")
        lines.append(f"Target: {state.target}")
        lines.append(f"Round: {state.round_index}")
        lines.append(f"Phase: {state.current_phase}")

        if top_candidates:
            lines.append("Top candidates:")
            for candidate in top_candidates:
                lines.append(
                    f"- {candidate.name} ({candidate.candidate_id})"
                    f" score={candidate.relevance_score} status={candidate.status}"
                )
        else:
            lines.append("Top candidates: none")

        if state.open_questions:
            lines.append("Open questions:")
            for question in state.open_questions:
                lines.append(
                    f"- [{question.priority}] ({question.owner_role}) {question.question}"
                    f" (subject={question.target_subject})"
                )
        else:
            lines.append("Open questions: none")

        if confirmed:
            lines.append("Confirmed candidates:")
            for candidate in confirmed:
                lines.append(f"- {candidate.name} ({candidate.candidate_id})")
        else:
            lines.append("Confirmed candidates: none")

        return "\n".join(lines).strip()
