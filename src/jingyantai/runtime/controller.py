from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import uuid4

from jingyantai.domain.models import BudgetPolicy, EvaluatorLogEvent, RunProgressEvent, RunState, RunTrace
from jingyantai.domain.phases import CandidateStatus, Phase, StopVerdict
from jingyantai.runtime.contracts import ContractJudge, ResearchSpec, RoundContract
from jingyantai.runtime.memory import FileMemoryStore, MemorySnapshot, RunMemoryEntry, WatchlistItem
from jingyantai.runtime.policies import DegradeAction, QualityRubric, RetryDecision, RuntimePolicy
from jingyantai.tools.contracts import ToolExecutionMetrics


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


_SKIP_ROLE = object()


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
        contract_builder: object | None = None,
        contract_judge: object | None = None,
        quality_rubric: object | None = None,
        runtime_policy: RuntimePolicy | None = None,
        memory_store: object | None = None,
        clock: object | None = None,
        progress_reporter: object | None = None,
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
        self.contract_builder = contract_builder
        self.quality_rubric = quality_rubric or QualityRubric.default()
        self.runtime_policy = runtime_policy or RuntimePolicy.default()
        self.contract_judge = contract_judge or ContractJudge(rubric=self.quality_rubric)
        self.memory_store = memory_store or self._build_default_memory_store(store)
        self.clock = clock or perf_counter
        self.progress_reporter = progress_reporter

    def run(self, *, target: str, budget: BudgetPolicy) -> RunState:
        state = RunState(
            run_id=self._new_run_id(),
            target=target,
            current_phase=Phase.INITIALIZE,
            budget=budget,
            resume_phase=Phase.INITIALIZE,
            resume_round_index=0,
        )
        self._hydrate_memory_inputs(state)
        state.carry_forward_context = self._memory_context_prefix()
        self._checkpoint(state)
        return self._run_state(state, run_started_at=self.clock())

    def resume(self, *, run_id: str, budget: BudgetPolicy | None = None) -> RunState:
        load_state = getattr(self.store, "load_state", None)
        if not callable(load_state):
            raise AttributeError("store does not support load_state")
        state = load_state(run_id)
        if budget is not None:
            state.budget = budget
        resume_phase, resume_round_index = self._resume_cursor(state)
        state.current_phase = resume_phase
        state.resume_phase = resume_phase
        state.resume_round_index = resume_round_index
        state.round_index = resume_round_index
        if state.current_phase == Phase.STOP:
            return state
        if not state.carry_forward_context:
            state.carry_forward_context = self._memory_context_prefix()
        self._checkpoint(state)
        return self._run_state(state, run_started_at=self.clock())

    def _new_run_id(self) -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        return f"run-{timestamp}-{uuid4().hex[:6]}"

    def _run_state(self, state: RunState, *, run_started_at: float) -> RunState:
        if state.current_phase == Phase.INITIALIZE:
            self._run_initialize_phase(state)
            control_reason = self._control_stop_reason(state, run_started_at)
            if control_reason is not None:
                self._stop_for_reason(state, control_reason)

        while state.current_phase != Phase.STOP and state.round_index <= state.budget.max_rounds:
            control_reason = self._control_stop_reason(state, run_started_at)
            if control_reason is not None:
                self._stop_for_reason(state, control_reason)
                break

            contract = None
            builder = self.contract_builder
            build_contract = getattr(builder, "build", None) if builder is not None else None
            if callable(build_contract):
                contract = build_contract(state)
            if contract is not None:
                contract = self._validate_round_contract(state, contract)
            self._persist_handoff_artifacts(state, contract)

            if state.current_phase == Phase.EXPAND:
                if self._should_expand(state):
                    self._run_expand_phase(state)
                    control_reason = self._control_stop_reason(state, run_started_at)
                    if control_reason is not None:
                        self._stop_for_reason(state, control_reason)
                        break
                state.current_phase = Phase.DEEPEN

            if state.current_phase == Phase.DEEPEN:
                self._run_deepen_phase(state)
                control_reason = self._control_stop_reason(state, run_started_at)
                if control_reason is not None:
                    self._stop_for_reason(state, control_reason)
                    break
                state.current_phase = Phase.CHALLENGE

            if state.current_phase == Phase.CHALLENGE:
                self._run_challenge_phase(state)
                control_reason = self._control_stop_reason(state, run_started_at)
                if control_reason is not None:
                    self._stop_for_reason(state, control_reason)
                    break
                state.current_phase = Phase.DECIDE

            if state.current_phase == Phase.DECIDE:
                if self._run_decide_phase(state):
                    break
                state.carry_forward_context = self._merge_memory_context(self.compactor.compact(state))
                state.round_index += 1
                state.current_phase = Phase.EXPAND

        if state.current_phase != Phase.STOP:
            round_budget_reason = self._round_budget_stop_reason(state)
            if round_budget_reason is not None:
                self._stop_for_reason(state, round_budget_reason)
            else:
                state.current_phase = Phase.STOP
                self._set_resume_cursor(state, Phase.STOP, state.round_index)

        self._persist_memory_outputs(state)
        self._checkpoint(state)
        return state

    def _run_initialize_phase(self, state: RunState) -> None:
        self._emit_progress(state, Phase.INITIALIZE, "start", "starting phase")
        initializer_started_at = self.clock()
        try:
            self._apply_phase_deadline_to_role_runtime(self.initializer, Phase.INITIALIZE.value, initializer_started_at)
            brief, charter = _invoke(self.initializer, state.target)
        finally:
            self._clear_phase_deadline_from_role_runtime(self.initializer)
        initializer_duration_ms = self._elapsed_ms(initializer_started_at)
        state.brief = brief
        state.charter = charter
        self._persist_research_spec(state)
        self._set_resume_cursor(state, Phase.EXPAND, state.round_index)
        self._trace(
            state,
            "created brief and charter",
            new_candidates=[],
            new_findings=[],
            review_decisions=[],
            role_timings_ms={self._role_name(self.initializer): initializer_duration_ms},
            phase_duration_ms=initializer_duration_ms,
        )
        state.current_phase = Phase.EXPAND

    def _run_expand_phase(self, state: RunState) -> None:
        state.current_phase = Phase.EXPAND
        self._emit_progress(state, Phase.EXPAND, "start", "starting phase")
        candidates_before = len(state.candidates)
        phase_started_at = self.clock()
        round_plan_started_at = self.clock()
        try:
            self._apply_phase_deadline_to_role_runtime(self.lead_researcher, Phase.EXPAND.value, phase_started_at)
            round_plan = _invoke(self.lead_researcher, state)
        finally:
            self._clear_phase_deadline_from_role_runtime(self.lead_researcher)
        role_timings_ms: dict[str, int] = {
            self._role_name(self.lead_researcher): self._elapsed_ms(round_plan_started_at)
        }
        tool_timings_ms: dict[str, int] = {}
        diagnostics: list[str] = []
        phase_external_fetches = 0
        role_errors: list[str] = []
        completed_scouts = 0
        phase_deadline_at = self._phase_deadline_at(Phase.EXPAND.value, phase_started_at)
        for scout in self.scouts:
            timeout_reason = None
            if completed_scouts > 0:
                timeout_reason = self._phase_timeout_reason(Phase.EXPAND.value, phase_started_at)
            if timeout_reason is not None:
                diagnostics.append(timeout_reason)
                break
            scout_name = self._role_name(scout)
            scout_started_at = self.clock()
            try:
                scout_deadline_at = self._deadline_share(
                    deadline_at=phase_deadline_at,
                    slots_remaining=max(len(self.scouts) - completed_scouts, 1),
                )
                self._apply_runtime_deadline_to_role_runtime(scout, scout_deadline_at)
                scout_result = self._invoke_with_retry(
                    state,
                    scout,
                    phase_name=Phase.EXPAND.value,
                    diagnostics=diagnostics,
                    args=(state,),
                )
                if scout_result is not _SKIP_ROLE:
                    for candidate in scout_result:
                        _advance_candidate_to_confirmed(candidate)
                        state.candidates.append(candidate)
            except Exception as exc:
                role_errors.append(self._format_role_error(scout, exc))
            finally:
                self._clear_phase_deadline_from_role_runtime(scout)
                role_timings_ms[scout_name] = role_timings_ms.get(scout_name, 0) + self._elapsed_ms(scout_started_at)
                phase_external_fetches += self._consume_role_metrics(state, scout, tool_timings_ms, diagnostics)
            completed_scouts += 1
            timeout_reason = self._phase_timeout_reason(Phase.EXPAND.value, phase_started_at)
            if timeout_reason is not None:
                diagnostics.append(timeout_reason)
                break
        self._set_resume_cursor(state, Phase.DEEPEN, state.round_index)
        self._trace(
            state,
            str(round_plan),
            new_candidates=[candidate.name for candidate in state.candidates[candidates_before:]],
            new_findings=[],
            review_decisions=[],
            role_errors=role_errors,
            diagnostics=diagnostics,
            role_timings_ms=role_timings_ms,
            tool_timings_ms=tool_timings_ms,
            phase_duration_ms=self._elapsed_ms(phase_started_at),
            external_fetches=phase_external_fetches,
        )

    def _run_deepen_phase(self, state: RunState) -> None:
        state.current_phase = Phase.DEEPEN
        self._emit_progress(state, Phase.DEEPEN, "start", "starting phase")
        findings_before = len(state.findings)
        phase_started_at = self.clock()
        deepen_targets = state.top_candidates(limit=state.budget.max_deepen_targets)
        phase_deadline_at = self._phase_deadline_at(Phase.DEEPEN.value, phase_started_at)
        total_analyst_runs = len(deepen_targets) * len(self.analysts)
        role_timings_ms: dict[str, int] = {}
        tool_timings_ms: dict[str, int] = {}
        diagnostics: list[str] = []
        phase_external_fetches = 0
        role_errors: list[str] = []
        phase_timed_out = False
        completed_analyst_runs = 0
        for candidate in deepen_targets:
            timeout_reason = None
            if completed_analyst_runs > 0:
                timeout_reason = self._phase_timeout_reason(Phase.DEEPEN.value, phase_started_at)
            if timeout_reason is not None:
                diagnostics.append(timeout_reason)
                phase_timed_out = True
                break
            for analyst in self.analysts:
                timeout_reason = None
                if completed_analyst_runs > 0:
                    timeout_reason = self._phase_timeout_reason(Phase.DEEPEN.value, phase_started_at)
                if timeout_reason is not None:
                    diagnostics.append(timeout_reason)
                    phase_timed_out = True
                    break
                analyst_name = self._role_name(analyst)
                analyst_started_at = self.clock()
                try:
                    analyst_deadline_at = self._deadline_share(
                        deadline_at=phase_deadline_at,
                        slots_remaining=max(total_analyst_runs - completed_analyst_runs, 1),
                    )
                    self._apply_runtime_deadline_to_role_runtime(analyst, analyst_deadline_at)
                    analyst_result = self._invoke_with_retry(
                        state,
                        analyst,
                        phase_name=Phase.DEEPEN.value,
                        diagnostics=diagnostics,
                        args=(state, candidate),
                    )
                    if analyst_result is not _SKIP_ROLE:
                        evidence, findings, uncertainties = analyst_result
                        state.evidence.extend(evidence)
                        state.findings.extend(findings)
                        state.uncertainties.extend(uncertainties)
                except Exception as exc:
                    role_errors.append(self._format_role_error(analyst, exc))
                finally:
                    self._clear_phase_deadline_from_role_runtime(analyst)
                    role_timings_ms[analyst_name] = role_timings_ms.get(analyst_name, 0) + self._elapsed_ms(analyst_started_at)
                    phase_external_fetches += self._consume_role_metrics(state, analyst, tool_timings_ms, diagnostics)
                completed_analyst_runs += 1
                timeout_reason = self._phase_timeout_reason(Phase.DEEPEN.value, phase_started_at)
                if timeout_reason is not None:
                    diagnostics.append(timeout_reason)
                    phase_timed_out = True
                    break
            if phase_timed_out:
                break
        self._set_resume_cursor(state, Phase.CHALLENGE, state.round_index)
        self._trace(
            state,
            "deepened top candidates",
            new_candidates=[],
            new_findings=[finding.finding_id for finding in state.findings[findings_before:]],
            review_decisions=[],
            role_errors=role_errors,
            diagnostics=diagnostics,
            role_timings_ms=role_timings_ms,
            tool_timings_ms=tool_timings_ms,
            phase_duration_ms=self._elapsed_ms(phase_started_at),
            external_fetches=phase_external_fetches,
        )

    def _run_challenge_phase(self, state: RunState) -> None:
        state.current_phase = Phase.CHALLENGE
        self._emit_progress(state, Phase.CHALLENGE, "start", "starting phase")
        phase_started_at = self.clock()
        reviews = [
            _invoke(self.evidence_judge, state),
            _invoke(self.coverage_judge, state),
            _invoke(self.challenger, state),
        ]
        state.review_decisions = [review for review in reviews if review is not None]
        for review in state.review_decisions:
            self._append_evaluator_log(
                state,
                phase=Phase.CHALLENGE,
                event_type="review_decision",
                judge_type=review.judge_type,
                verdict=review.verdict.value,
                target_scope=review.target_scope,
                reasons=review.reasons,
                required_actions=review.required_actions,
            )
        self._set_resume_cursor(state, Phase.DECIDE, state.round_index)
        self._trace(
            state,
            "completed challenge phase",
            new_candidates=[],
            new_findings=[],
            review_decisions=[decision.judge_type for decision in state.review_decisions],
            phase_duration_ms=self._elapsed_ms(phase_started_at),
        )

    def _run_decide_phase(self, state: RunState) -> bool:
        state.current_phase = Phase.DECIDE
        self._emit_progress(state, Phase.DECIDE, "start", "starting phase")
        phase_started_at = self.clock()
        stop_decision = _invoke(self.stop_judge, state)
        next_round_index = state.round_index + 1
        if stop_decision is None:
            self._set_resume_cursor(state, Phase.EXPAND, next_round_index)
            self._trace(
                state,
                "no stop decision",
                new_candidates=[],
                new_findings=[],
                review_decisions=[],
                diagnostics=["stop judge returned no decision"],
                phase_duration_ms=self._elapsed_ms(phase_started_at),
            )
            return False
        state.gap_tickets = stop_decision.gap_tickets
        self._append_evaluator_log(
            state,
            phase=Phase.DECIDE,
            event_type="stop_decision",
            judge_type="stop",
            verdict=stop_decision.verdict.value,
            target_scope="run",
            reasons=stop_decision.reasons,
            required_actions=[ticket.acceptance_rule for ticket in stop_decision.gap_tickets],
            stop_reason=state.stop_reason,
        )
        if stop_decision.verdict == StopVerdict.STOP:
            self._set_resume_cursor(state, Phase.STOP, state.round_index)
        else:
            self._set_resume_cursor(state, Phase.EXPAND, next_round_index)
        self._trace(
            state,
            stop_decision.verdict.value,
            new_candidates=[],
            new_findings=[],
            review_decisions=[],
            phase_duration_ms=self._elapsed_ms(phase_started_at),
        )
        if stop_decision.verdict == StopVerdict.STOP:
            state.current_phase = Phase.STOP
            return True
        return False

    def _build_default_memory_store(self, store: object) -> FileMemoryStore | None:
        root_dir = getattr(store, "_root_dir", None)
        if root_dir is None:
            return None
        return FileMemoryStore(root_dir)

    def _resume_cursor(self, state: RunState) -> tuple[Phase, int]:
        if state.resume_phase is not None:
            return state.resume_phase, state.resume_round_index or state.round_index
        if state.current_phase == Phase.STOP:
            return Phase.STOP, state.round_index
        if not state.traces:
            return state.current_phase, state.round_index

        last_phase = state.traces[-1].phase
        if last_phase == Phase.INITIALIZE:
            return Phase.EXPAND, state.round_index
        if last_phase == Phase.EXPAND:
            return Phase.DEEPEN, state.round_index
        if last_phase == Phase.DEEPEN:
            return Phase.CHALLENGE, state.round_index
        if last_phase == Phase.CHALLENGE:
            return Phase.DECIDE, state.round_index
        if last_phase == Phase.DECIDE:
            if state.stop_reason or state.current_phase == Phase.STOP:
                return Phase.STOP, state.round_index
            return Phase.EXPAND, state.round_index + 1
        return state.current_phase, state.round_index

    def _set_resume_cursor(self, state: RunState, phase: Phase, round_index: int) -> None:
        state.resume_phase = phase
        state.resume_round_index = round_index

    def _should_expand(self, state: RunState) -> bool:
        if state.round_index == 0:
            return True
        if any(ticket.owner_role == "scout" for ticket in state.gap_tickets):
            return True

        min_confirmed = self._min_confirmed_candidates()
        if min_confirmed is not None and self._confirmed_candidate_count(state) < min_confirmed:
            return True

        # Avoid stalling if nothing is eligible for DEEPEN.
        if not state.top_candidates(limit=1):
            return True

        return False

    def _min_confirmed_candidates(self) -> int | None:
        stop_bar = getattr(self.stop_judge, "stop_bar", None)
        min_confirmed = getattr(stop_bar, "min_confirmed_candidates", None)
        if isinstance(min_confirmed, int) and min_confirmed > 0:
            return min_confirmed
        return None

    def _confirmed_candidate_count(self, state: RunState) -> int:
        return sum(
            1
            for candidate in state.candidates
            if getattr(candidate, "status", None) == CandidateStatus.CONFIRMED
        )

    def _role_name(self, role: object) -> str:
        return str(getattr(role, "role_name", type(role).__name__))

    def _elapsed_ms(self, started_at: float) -> int:
        return max(int((self.clock() - started_at) * 1000), 0)

    def _merge_timings(self, target: dict[str, int], extra: dict[str, int]) -> None:
        for name, value in extra.items():
            target[name] = target.get(name, 0) + value

    def _merge_fetch_breakdown(self, target: dict[str, int], extra: dict[str, int]) -> None:
        for name, value in extra.items():
            target[name] = target.get(name, 0) + value

    def _merge_tool_metrics(self, target: ToolExecutionMetrics, extra: ToolExecutionMetrics) -> None:
        target.external_fetches += extra.external_fetches
        self._merge_fetch_breakdown(target.fetch_breakdown, extra.fetch_breakdown)
        self._merge_timings(target.timings_ms, extra.timings_ms)
        target.notes.extend(extra.notes)

    def _phase_timeout_reason(self, phase_name: str, phase_started_at: float) -> str | None:
        phase_policy = self.runtime_policy.phase_policies.get(phase_name)
        if phase_policy is None:
            return None
        elapsed_seconds = self.clock() - phase_started_at
        if elapsed_seconds > phase_policy.soft_timeout_seconds:
            return (
                f"soft timeout exceeded for phase {phase_name}: "
                f"{elapsed_seconds:.3f}/{phase_policy.soft_timeout_seconds:.3f}s"
            )
        return None

    def _phase_deadline_at(self, phase_name: str, phase_started_at: float) -> float | None:
        phase_policy = self.runtime_policy.phase_policies.get(phase_name)
        if phase_policy is None:
            return None
        return phase_started_at + phase_policy.soft_timeout_seconds

    def _deadline_share(
        self,
        *,
        deadline_at: float | None,
        slots_remaining: int,
    ) -> float | None:
        if deadline_at is None:
            return None
        if slots_remaining <= 1:
            return deadline_at
        remaining_seconds = max(deadline_at - self.clock(), 0.0)
        return min(deadline_at, self.clock() + (remaining_seconds / slots_remaining))

    def _set_runtime_deadline_on_target(self, target: object | None, deadline_at: float | None) -> None:
        if target is None:
            return
        set_deadline = getattr(target, "set_runtime_deadline", None)
        if callable(set_deadline):
            set_deadline(deadline_at)

    def _clear_runtime_deadline_on_target(self, target: object | None) -> None:
        if target is None:
            return
        clear_deadline = getattr(target, "clear_runtime_deadline", None)
        if callable(clear_deadline):
            clear_deadline()

    def _apply_runtime_deadline_to_role_runtime(self, role: object, deadline_at: float | None) -> None:
        self._set_runtime_deadline_on_target(role, deadline_at)
        self._set_runtime_deadline_on_target(getattr(role, "adapter", None), deadline_at)
        self._set_runtime_deadline_on_target(getattr(role, "tools", None), deadline_at)

    def _apply_phase_deadline_to_role_runtime(self, role: object, phase_name: str, phase_started_at: float) -> None:
        deadline_at = self._phase_deadline_at(phase_name, phase_started_at)
        self._apply_runtime_deadline_to_role_runtime(role, deadline_at)

    def _clear_phase_deadline_from_role_runtime(self, role: object) -> None:
        self._clear_runtime_deadline_on_target(role)
        self._clear_runtime_deadline_on_target(getattr(role, "adapter", None))
        self._clear_runtime_deadline_on_target(getattr(role, "tools", None))

    def _runtime_deadline_active_on_target(self, target: object | None) -> bool:
        if target is None:
            return False
        remaining_timeout = getattr(target, "_remaining_timeout_seconds", None)
        if callable(remaining_timeout):
            return remaining_timeout() is not None
        return getattr(target, "_runtime_deadline_at", None) is not None

    def _role_runtime_deadline_active(self, role: object) -> bool:
        return any(
            self._runtime_deadline_active_on_target(target)
            for target in (
                role,
                getattr(role, "adapter", None),
                getattr(role, "tools", None),
            )
        )

    def _apply_degrade_action(
        self,
        state: RunState,
        role: object,
        action: DegradeAction | None,
        diagnostics: list[str],
    ) -> None:
        if action is None:
            diagnostics.append(f"{self._role_name(role)} degraded without explicit action")
            return

        if action == DegradeAction.REDUCE_SEARCH_RESULTS:
            current = int(getattr(role, "search_max_results", 5))
            setattr(role, "search_max_results", max(1, current - 1))
        elif action == DegradeAction.USE_CACHED_RESULTS_ONLY:
            setattr(role, "cache_only", True)
        elif action == DegradeAction.FALLBACK_GITHUB_ONLY:
            setattr(role, "source_mix", ["github"])
        elif action == DegradeAction.REDUCE_DEEPEN_TARGETS:
            state.budget.max_deepen_targets = max(1, state.budget.max_deepen_targets - 1)
        elif action == DegradeAction.SKIP_SLOWEST_CANDIDATES:
            state.budget.max_deepen_targets = max(1, state.budget.max_deepen_targets - 1)

        diagnostics.append(f"{self._role_name(role)} applied degrade action: {action.value}")

    def _invoke_with_retry(
        self,
        state: RunState,
        role: object,
        *,
        phase_name: str,
        diagnostics: list[str],
        args: tuple[Any, ...],
    ) -> Any:
        attempt = 1
        while True:
            try:
                return _invoke(role, *args)
            except Exception as exc:
                self._stash_role_metrics(role)
                error_kind = self._classify_error(exc)
                outcome = self.runtime_policy.retry_policy.decide(
                    error_kind=error_kind,
                    attempt=attempt,
                    phase_name=phase_name,
                )
                if (
                    outcome.decision == RetryDecision.RETRY
                    and error_kind == "timeout"
                    and attempt >= 2
                    and self._role_runtime_deadline_active(role)
                ):
                    diagnostics.append(
                        f"{self._role_name(role)} degraded after {error_kind} "
                        f"(attempt {attempt})"
                    )
                    phase_policy = self.runtime_policy.phase_policies.get(phase_name)
                    degrade_action = phase_policy.degrade_on[0] if phase_policy and phase_policy.degrade_on else None
                    self._apply_degrade_action(state, role, degrade_action, diagnostics)
                    return _SKIP_ROLE
                if outcome.decision == RetryDecision.RETRY:
                    diagnostics.append(
                        f"{self._role_name(role)} retrying after {error_kind} "
                        f"(attempt {attempt})"
                    )
                    attempt += 1
                    continue
                if outcome.decision == RetryDecision.DEGRADE:
                    diagnostics.append(
                        f"{self._role_name(role)} degraded after {error_kind} "
                        f"(attempt {attempt})"
                    )
                    self._apply_degrade_action(state, role, outcome.degrade_action, diagnostics)
                    return _SKIP_ROLE
                if outcome.decision == RetryDecision.SKIP:
                    diagnostics.append(
                        f"{self._role_name(role)} skipped after {error_kind} "
                        f"(attempt {attempt})"
                    )
                    return _SKIP_ROLE
                raise exc

    def _consume_role_metrics(
        self,
        state: RunState,
        role: object,
        tool_timings_ms: dict[str, int],
        diagnostics: list[str],
    ) -> int:
        metrics = self._pop_role_metrics(role)
        if metrics is None:
            return 0
        self._merge_timings(tool_timings_ms, metrics.timings_ms)
        self._merge_fetch_breakdown(state.external_fetch_breakdown, metrics.fetch_breakdown)
        diagnostics.extend(metrics.notes)
        state.external_fetch_count += metrics.external_fetches
        return metrics.external_fetches

    def _pop_role_metrics(self, role: object) -> ToolExecutionMetrics | None:
        pending = getattr(role, "_pending_tool_metrics", None)
        current = getattr(role, "last_tool_metrics", None)
        setattr(role, "_pending_tool_metrics", None)
        setattr(role, "last_tool_metrics", None)
        merged = ToolExecutionMetrics()
        has_metrics = False
        for metrics in (pending, current):
            if not isinstance(metrics, ToolExecutionMetrics):
                continue
            self._merge_tool_metrics(merged, metrics)
            has_metrics = True
        return merged if has_metrics else None

    def _stash_role_metrics(self, role: object) -> None:
        metrics = getattr(role, "last_tool_metrics", None)
        if not isinstance(metrics, ToolExecutionMetrics):
            return
        pending = getattr(role, "_pending_tool_metrics", None)
        if not isinstance(pending, ToolExecutionMetrics):
            pending = ToolExecutionMetrics()
        self._merge_tool_metrics(pending, metrics)
        setattr(role, "_pending_tool_metrics", pending)
        setattr(role, "last_tool_metrics", None)

    def _control_stop_reason(self, state: RunState, run_started_at: float) -> str | None:
        cancel_reason = self._cancel_stop_reason(state)
        if cancel_reason is not None:
            return cancel_reason
        return self._budget_stop_reason(state, run_started_at)

    def _cancel_stop_reason(self, state: RunState) -> str | None:
        load_cancel_request = getattr(self.store, "load_cancel_request", None)
        if not callable(load_cancel_request):
            return None
        return load_cancel_request(state.run_id)

    def _budget_stop_reason(self, state: RunState, run_started_at: float) -> str | None:
        if state.external_fetch_count > state.budget.max_external_fetches:
            breakdown = ""
            if state.external_fetch_breakdown:
                breakdown = " (" + ", ".join(
                    f"{name}={count}" for name, count in sorted(state.external_fetch_breakdown.items())
                ) + ")"
            return (
                "external fetch budget exceeded: "
                f"{state.external_fetch_count}/{state.budget.max_external_fetches}{breakdown}"
            )
        elapsed_minutes = (self.clock() - run_started_at) / 60
        if elapsed_minutes > state.budget.max_run_duration_minutes:
            return (
                "run duration budget exceeded: "
                f"{elapsed_minutes:.2f}/{state.budget.max_run_duration_minutes} minutes"
            )
        return None

    def _round_budget_stop_reason(self, state: RunState) -> str | None:
        if state.round_index > state.budget.max_rounds:
            return (
                "round budget exhausted: "
                f"next round {state.round_index} exceeds max_rounds={state.budget.max_rounds}"
            )
        return None

    def _stop_for_reason(self, state: RunState, reason: str) -> None:
        state.stop_reason = reason
        self._set_resume_cursor(state, Phase.STOP, state.round_index)
        self._append_evaluator_log(
            state,
            phase=state.current_phase,
            event_type="forced_stop",
            judge_type="stop",
            verdict=StopVerdict.STOP.value,
            target_scope="run",
            reasons=[reason],
            stop_reason=reason,
        )
        state.current_phase = Phase.STOP
        self._trace(
            state,
            reason,
            new_candidates=[],
            new_findings=[],
            review_decisions=[],
            diagnostics=[reason],
            stop_or_continue=StopVerdict.STOP.value,
        )

    def _validate_round_contract(self, state: RunState, contract: object) -> RoundContract:
        try:
            validated = RoundContract.model_validate(contract)
        except Exception as exc:
            self._append_evaluator_log(
                state,
                phase=state.current_phase,
                event_type="contract_rejected",
                judge_type="contract",
                verdict="reject",
                target_scope="round_contract",
                reasons=["RoundContract produced by contract_builder is not valid."],
            )
            raise ValueError("RoundContract produced by contract_builder is not valid.") from exc

        decision = _invoke(self.contract_judge, validated)
        if not bool(getattr(decision, "is_valid", False)):
            reasons = getattr(decision, "reasons", None) or []
            normalized_reasons = [str(item) for item in reasons] if reasons else ["unknown reason"]
            self._append_evaluator_log(
                state,
                phase=state.current_phase,
                event_type="contract_rejected",
                judge_type="contract",
                verdict="reject",
                target_scope=validated.target_scope,
                reasons=normalized_reasons,
            )
            reason_blob = "; ".join(str(item) for item in reasons) if reasons else "unknown reason"
            raise ValueError(f"RoundContract produced by contract_builder is not acceptable: {reason_blob}")

        return validated

    def _build_research_spec(self, state: RunState) -> ResearchSpec | None:
        if state.brief is None or state.charter is None:
            return None
        return ResearchSpec(
            target=state.target,
            mission=state.charter.mission,
            product_type=state.brief.product_type,
            competitor_definition=state.brief.competitor_definition,
            scope=list(state.charter.scope),
            non_goals=list(state.charter.non_goals),
            required_dimensions=list(state.brief.required_dimensions),
            success_criteria=list(state.charter.success_criteria),
            research_agenda=list(state.charter.research_agenda),
            stop_policy=state.brief.stop_policy,
            budget=state.budget,
            quality_rubric=self.quality_rubric,
        )

    def _persist_research_spec(self, state: RunState) -> None:
        research_spec = self._build_research_spec(state)
        if research_spec is None:
            return
        save_research_spec = getattr(self.store, "save_research_spec", None)
        if callable(save_research_spec):
            save_research_spec(state.run_id, research_spec)

    def _persist_handoff_artifacts(self, state: RunState, contract: object | None) -> None:
        if contract is None:
            return
        save_round_contract = getattr(self.store, "save_round_contract", None)
        if callable(save_round_contract):
            save_round_contract(state.run_id, state.round_index, contract)

    def _append_evaluator_log(
        self,
        state: RunState,
        *,
        phase: Phase,
        event_type: str,
        judge_type: str | None = None,
        verdict: str | None = None,
        target_scope: str | None = None,
        reasons: list[str] | None = None,
        required_actions: list[str] | None = None,
        stop_reason: str | None = None,
    ) -> None:
        event = EvaluatorLogEvent(
            run_id=state.run_id,
            round_index=state.round_index,
            phase=phase,
            event_type=event_type,
            judge_type=judge_type,
            verdict=verdict,
            target_scope=target_scope,
            reasons=list(reasons or []),
            required_actions=list(required_actions or []),
            stop_reason=stop_reason,
        )
        append_evaluator_log = getattr(self.store, "append_evaluator_log", None)
        if callable(append_evaluator_log):
            append_evaluator_log(state.run_id, event)

    def _hydrate_memory_inputs(self, state: RunState) -> None:
        memory_store = self.memory_store
        if memory_store is None:
            return

        load_snapshot = getattr(memory_store, "load_snapshot", None)
        if callable(load_snapshot):
            snapshot = load_snapshot()
            if isinstance(snapshot, MemorySnapshot):
                state.memory_snapshot = snapshot.model_dump(mode="json")

        load_watchlist = getattr(memory_store, "load_watchlist", None)
        if callable(load_watchlist):
            items = load_watchlist()
            state.watchlist = [
                item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
                for item in items
            ]

        load_memory = getattr(memory_store, "load_memory", None)
        if callable(load_memory):
            state.historical_memory = self._build_historical_memory_payload(state.target, load_memory())

    def _memory_context_prefix(self) -> str:
        memory_store = self.memory_store
        if memory_store is None:
            return ""
        load_snapshot = getattr(memory_store, "load_snapshot", None)
        if not callable(load_snapshot):
            return ""
        snapshot = load_snapshot()
        if not isinstance(snapshot, MemorySnapshot):
            return ""
        return self._format_memory_snapshot(snapshot)

    def _format_memory_snapshot(self, snapshot: MemorySnapshot) -> str:
        parts: list[str] = []
        if snapshot.top_competitors:
            parts.append("历史重点竞品: " + ", ".join(snapshot.top_competitors))
        if snapshot.unresolved_uncertainties:
            parts.append("历史未解问题: " + "; ".join(snapshot.unresolved_uncertainties))
        if snapshot.trusted_sources:
            parts.append("历史可信来源: " + ", ".join(snapshot.trusted_sources))
        if snapshot.repeated_failure_patterns:
            parts.append("历史失败模式: " + "; ".join(snapshot.repeated_failure_patterns))
        if not parts:
            return ""
        return "历史研究快照\n" + "\n".join(parts)

    def _merge_memory_context(self, dynamic_context: str) -> str:
        memory_context = self._memory_context_prefix()
        dynamic_context = dynamic_context.strip()
        if memory_context and dynamic_context:
            return f"{memory_context}\n\n{dynamic_context}"
        return memory_context or dynamic_context

    def _persist_memory_outputs(self, state: RunState) -> None:
        memory_store = self.memory_store
        if memory_store is None:
            return

        save_snapshot = getattr(memory_store, "save_snapshot", None)
        if callable(save_snapshot):
            save_snapshot(self._build_memory_snapshot(state))

        save_watchlist = getattr(memory_store, "save_watchlist", None)
        if callable(save_watchlist):
            save_watchlist(self._build_watchlist(state))

        load_memory = getattr(memory_store, "load_memory", None)
        save_memory = getattr(memory_store, "save_memory", None)
        if callable(load_memory) and callable(save_memory):
            existing = [entry for entry in load_memory() if getattr(entry, "run_id", None) != state.run_id]
            existing.append(self._build_memory_entry(state))
            save_memory(existing)

    def _build_memory_snapshot(self, state: RunState) -> MemorySnapshot:
        confirmed = [
            candidate
            for candidate in sorted(
                state.candidates,
                key=lambda candidate: getattr(candidate, "relevance_score", 0.0),
                reverse=True,
            )
            if getattr(candidate, "status", None) == CandidateStatus.CONFIRMED
        ]
        top_competitors = list(dict.fromkeys(candidate.name for candidate in confirmed))
        uncertainty_items = [
            getattr(item, "statement", "")
            for item in state.uncertainties
            if getattr(item, "statement", "")
        ]
        review_reasons = [
            reason
            for review in state.review_decisions
            if str(getattr(getattr(review, "verdict", None), "value", getattr(review, "verdict", ""))).lower() != "pass"
            for reason in getattr(review, "reasons", [])
            if reason
        ]
        gap_reasons = [ticket.blocking_reason for ticket in state.gap_tickets if ticket.blocking_reason]
        unresolved_uncertainties = list(
            dict.fromkeys([*uncertainty_items, *review_reasons, *gap_reasons])
        )
        trusted_sources = list(
            dict.fromkeys(getattr(item, "source_url", "") for item in state.evidence if getattr(item, "source_url", ""))
        )
        diagnostic_failures = [
            diagnostic
            for trace in state.traces
            for diagnostic in getattr(trace, "diagnostics", [])
            if "timeout" in diagnostic.lower() or "failed" in diagnostic.lower()
        ]
        repeated_failure_patterns = list(
            dict.fromkeys(
                [
                    *[error for trace in state.traces for error in getattr(trace, "role_errors", [])],
                    *diagnostic_failures,
                ]
            )
        )
        return MemorySnapshot(
            top_competitors=top_competitors,
            unresolved_uncertainties=unresolved_uncertainties,
            trusted_sources=trusted_sources,
            repeated_failure_patterns=repeated_failure_patterns,
        )

    def _build_watchlist(self, state: RunState) -> list[WatchlistItem]:
        candidates_by_name = {
            candidate.name: candidate
            for candidate in state.candidates
            if getattr(candidate, "status", None) == CandidateStatus.CONFIRMED
        }
        items: list[WatchlistItem] = []
        seen: set[tuple[str, str]] = set()
        for ticket in state.gap_tickets:
            candidate = candidates_by_name.get(ticket.target_scope)
            if candidate is None:
                continue
            key = (candidate.name, ticket.blocking_reason)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                WatchlistItem(
                    entity_name=candidate.name,
                    canonical_url=candidate.canonical_url,
                    watch_reason=ticket.blocking_reason,
                    revisit_trigger=ticket.acceptance_rule,
                    priority=str(getattr(ticket.priority, "value", ticket.priority)),
                    last_seen_run_id=state.run_id,
                )
            )
        for review in state.review_decisions:
            judge_type = str(getattr(review, "judge_type", ""))
            verdict = str(getattr(getattr(review, "verdict", None), "value", getattr(review, "verdict", ""))).lower()
            if judge_type != "coverage" or verdict == "pass":
                continue
            for reason in getattr(review, "reasons", []):
                entity_name, separator, missing_dimensions = str(reason).partition(" missing: ")
                if not separator:
                    continue
                candidate = candidates_by_name.get(entity_name)
                if candidate is None:
                    continue
                watch_reason = f"Missing dimensions: {missing_dimensions}"
                key = (candidate.name, watch_reason)
                if key in seen:
                    continue
                seen.add(key)
                items.append(
                    WatchlistItem(
                        entity_name=candidate.name,
                        canonical_url=candidate.canonical_url,
                        watch_reason=watch_reason,
                        revisit_trigger="Cover all required dimensions with direct evidence.",
                        priority="high",
                        last_seen_run_id=state.run_id,
                    )
                )
        return items

    def _build_memory_entry(self, state: RunState) -> RunMemoryEntry:
        snapshot = self._build_memory_snapshot(state)
        return RunMemoryEntry(
            run_id=state.run_id,
            target=state.target,
            confirmed_entities=snapshot.top_competitors,
            unresolved_uncertainties=snapshot.unresolved_uncertainties,
            trusted_sources=snapshot.trusted_sources,
            repeated_failure_patterns=snapshot.repeated_failure_patterns,
        )

    def _build_historical_memory_payload(self, target: str, entries: list[object]) -> dict[str, Any]:
        matching_entries = [
            entry
            for entry in entries
            if isinstance(entry, RunMemoryEntry) and entry.target == target
        ]
        if not matching_entries:
            return {}

        recent_entries = matching_entries[-3:]
        return {
            "recent_runs": [entry.model_dump(mode="json") for entry in recent_entries],
            "recurring_competitors": self._dedupe_strings(
                name
                for entry in recent_entries
                for name in entry.confirmed_entities
            )[:5],
            "recurring_uncertainties": self._dedupe_strings(
                item
                for entry in recent_entries
                for item in entry.unresolved_uncertainties
            )[:5],
            "recurring_trusted_sources": self._dedupe_strings(
                source
                for entry in recent_entries
                for source in entry.trusted_sources
            )[:5],
            "recurring_failure_patterns": self._dedupe_strings(
                pattern
                for entry in recent_entries
                for pattern in entry.repeated_failure_patterns
            )[:5],
        }

    def _dedupe_strings(self, values: Any) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for value in values:
            normalized = str(value).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    def _classify_error(self, error: Exception) -> str:
        error_type = type(error).__name__.lower()
        message = str(error).lower()
        if "timeout" in error_type or "timeout" in message:
            return "timeout"
        if "providerrequest" in error_type or "httperror" in error_type:
            return "provider_request"
        if "validation" in error_type or "schema" in message:
            return "schema_validation"
        if "extract" in error_type or "extract" in message:
            return "page_extract_failure"
        if "search" in message or "github" in message or "fetch" in message:
            return "tool_fetch"
        if "url" in message or "404" in message or "unreachable" in message:
            return "bad_candidate"
        return "runtime_error"

    def _format_role_error(self, role: object, error: Exception) -> str:
        role_name = self._role_name(role)
        provider = str(getattr(role, "provider", "unknown"))
        model = str(getattr(role, "model", "unknown"))
        error_kind = self._classify_error(error)
        return f"{role_name}|{provider}|{model}|{error_kind}|{type(error).__name__}|{error}"

    def _trace(
        self,
        state: RunState,
        planner_output: str,
        *,
        new_candidates: list[str],
        new_findings: list[str],
        review_decisions: list[str],
        role_errors: list[str] | None = None,
        diagnostics: list[str] | None = None,
        role_timings_ms: dict[str, int] | None = None,
        tool_timings_ms: dict[str, int] | None = None,
        phase_duration_ms: int = 0,
        external_fetches: int = 0,
        stop_or_continue: str | None = None,
    ) -> None:
        trace = RunTrace(
            round_index=state.round_index,
            phase=state.current_phase,
            planner_output=planner_output,
            dispatched_tasks=[],
            new_candidates=list(new_candidates),
            new_findings=list(new_findings),
            review_decisions=list(review_decisions),
            stop_or_continue=stop_or_continue or state.current_phase.value,
            role_errors=list(role_errors or []),
            diagnostics=list(diagnostics or []),
            role_timings_ms=dict(role_timings_ms or {}),
            tool_timings_ms=dict(tool_timings_ms or {}),
            phase_duration_ms=phase_duration_ms,
            external_fetches=external_fetches,
        )
        state.traces.append(trace)
        self._checkpoint(state, trace)
        self._emit_progress(state, state.current_phase, "end", planner_output)

    def _checkpoint(self, state: RunState, trace: RunTrace | None = None) -> None:
        save_state = getattr(self.store, "save_state", None)
        if callable(save_state):
            save_state(state)

        if trace is None:
            return
        append_trace = getattr(self.store, "append_trace", None)
        if callable(append_trace):
            append_trace(state.run_id, trace)

    def _emit_progress(self, state: RunState, phase: Phase, stage: str, message: str) -> None:
        event = RunProgressEvent(
            run_id=state.run_id,
            round_index=state.round_index,
            phase=phase,
            stage=stage,
            message=message,
            candidate_count=len(state.candidates),
            finding_count=len(state.findings),
            external_fetch_count=state.external_fetch_count,
            stop_reason=state.stop_reason,
        )

        append_progress_log = getattr(self.store, "append_progress_log", None)
        if callable(append_progress_log):
            append_progress_log(state.run_id, event)

        reporter = self.progress_reporter
        if callable(reporter):
            reporter(event)
