from __future__ import annotations

from jingyantai.domain.models import RunState
from jingyantai.domain.phases import CandidateStatus


class ContextCompactor:
    def compact(self, state: RunState) -> str:
        """Produce a carry-forward snapshot string for the next round/phase."""

        top = state.top_candidates(limit=1)
        confirmed = [candidate for candidate in state.candidates if candidate.status == CandidateStatus.CONFIRMED]

        lines: list[str] = []
        lines.append("CARRY-FORWARD SNAPSHOT")
        lines.append(f"Target: {state.target}")
        lines.append(f"Round: {state.round_index}")
        lines.append(f"Phase: {state.current_phase}")

        if top:
            candidate = top[0]
            lines.append("Top candidate:")
            lines.append(f"- {candidate.name} ({candidate.candidate_id}) {candidate.canonical_url}")
        else:
            lines.append("Top candidate: none")

        if confirmed:
            lines.append("Confirmed candidates:")
            for candidate in confirmed:
                lines.append(f"- {candidate.name} ({candidate.candidate_id})")
        else:
            lines.append("Confirmed candidates: none")

        return "\n".join(lines).strip()
