from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from jingyantai.domain.models import BudgetPolicy, RunState, RunTrace
from jingyantai.domain.phases import CandidateStatus, Phase, StopVerdict


def _invoke(agent: object, *args: Any) -> Any:
    runner = getattr(agent, "run", None)
    if callable(runner):
        return runner(*args)
    if callable(agent):
        return agent(*args)
    raise TypeError(f"Agent {agent!r} is not callable and does not expose run().")


def _advance_candidate_to_confirmed(candidate: object) -> None:
    status = getattr(candidate, "status", None)
    progression = [
        CandidateStatus.DISCOVERED,
        CandidateStatus.NORMALIZED,
        CandidateStatus.PLAUSIBLE,
        CandidateStatus.PRIORITIZED,
        CandidateStatus.CONFIRMED,
    ]
    if status not in progression:
        return

    while getattr(candidate, "status", None) != CandidateStatus.CONFIRMED:
        current = getattr(candidate, "status")
        next_status = progression[progression.index(current) + 1]
        candidate.transition_to(next_status)


class HarnessController:
    def __init__(
        self,
        *,
        store: object,
        initializer: object,
        lead_researcher: object,
        scouts: list[object],
        analysts: list[object],
        compactor: object,
        evidence_judge: object,
        coverage_judge: object,
        challenger: object,
        stop_judge: object,
    ) -> None:
        self.store = store
        self.initializer = initializer
        self.lead_researcher = lead_researcher
        self.scouts = list(scouts)
        self.analysts = list(analysts)
        self.compactor = compactor
        self.evidence_judge = evidence_judge
        self.coverage_judge = coverage_judge
        self.challenger = challenger
        self.stop_judge = stop_judge

    def run(self, *, target: str, budget: BudgetPolicy) -> RunState:
        run_id = datetime.now(UTC).strftime("run-%Y%m%d%H%M%S")
        state = RunState(
            run_id=run_id,
            target=target,
            current_phase=Phase.INITIALIZE,
            budget=budget,
        )

        brief, charter = _invoke(self.initializer, target)
        state.brief = brief
        state.charter = charter
        self._trace(state, "created brief and charter")

        while state.round_index <= state.budget.max_rounds:
            if state.round_index == 0 or any(ticket.owner_role == "scout" for ticket in state.gap_tickets):
                state.current_phase = Phase.EXPAND
                round_plan = _invoke(self.lead_researcher, state)
                role_errors: list[str] = []
                for scout in self.scouts:
                    try:
                        for candidate in _invoke(scout, state):
                            _advance_candidate_to_confirmed(candidate)
                            state.candidates.append(candidate)
                    except Exception as exc:
                        role_errors.append(self._format_role_error(scout, exc))
                self._trace(state, str(round_plan), role_errors=role_errors)

            state.current_phase = Phase.DEEPEN
            role_errors: list[str] = []
            for candidate in state.top_candidates(limit=state.budget.max_deepen_targets):
                for analyst in self.analysts:
                    try:
                        evidence, findings, uncertainties = _invoke(analyst, state, candidate)
                        state.evidence.extend(evidence)
                        state.findings.extend(findings)
                        state.uncertainties.extend(uncertainties)
                    except Exception as exc:
                        role_errors.append(self._format_role_error(analyst, exc))
            self._trace(state, "deepened top candidates", role_errors=role_errors)

            state.current_phase = Phase.CHALLENGE
            reviews = [
                _invoke(self.evidence_judge, state),
                _invoke(self.coverage_judge, state),
                _invoke(self.challenger, state),
            ]
            state.review_decisions.extend([review for review in reviews if review is not None])
            self._trace(state, "completed challenge phase")

            state.current_phase = Phase.DECIDE
            stop_decision = _invoke(self.stop_judge, state)
            state.gap_tickets = stop_decision.gap_tickets
            self._trace(state, stop_decision.verdict.value)
            if stop_decision.verdict == StopVerdict.STOP:
                state.current_phase = Phase.STOP
                break

            state.carry_forward_context = self.compactor.compact(state)
            state.round_index += 1

        if state.current_phase != Phase.STOP:
            state.current_phase = Phase.STOP

        self.store.save_state(state)
        for trace in state.traces:
            self.store.append_trace(state.run_id, trace)
        return state

    def _format_role_error(self, role: object, error: Exception) -> str:
        role_name = str(getattr(role, "role_name", type(role).__name__))
        provider = str(getattr(role, "provider", "unknown"))
        model = str(getattr(role, "model", "unknown"))
        return f"{role_name}|{provider}|{model}|{type(error).__name__}|{error}"

    def _trace(self, state: RunState, planner_output: str, *, role_errors: list[str] | None = None) -> None:
        trace = RunTrace(
            round_index=state.round_index,
            phase=state.current_phase,
            planner_output=planner_output,
            dispatched_tasks=[],
            new_candidates=[candidate.name for candidate in state.candidates],
            new_findings=[finding.finding_id for finding in state.findings],
            review_decisions=[decision.judge_type for decision in state.review_decisions],
            stop_or_continue=state.current_phase.value,
            role_errors=list(role_errors or []),
        )
        state.traces.append(trace)
