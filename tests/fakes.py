from __future__ import annotations

from jingyantai.domain.models import BudgetPolicy, ResearchBrief, RunCharter, StopDecision
from jingyantai.domain.phases import StopVerdict


class FakeInitializer:
    """Deterministic test double for the initializer agent."""

    def run(self, target: str) -> tuple[ResearchBrief, RunCharter]:
        # ResearchBrief requires a BudgetPolicy; keep a minimal, valid default.
        budget = BudgetPolicy(
            max_rounds=4,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        )
        brief = ResearchBrief(
            target=target,
            product_type="developer tool",
            competitor_definition="Tools that solve the same job-to-be-done for the same user segment.",
            required_dimensions=["positioning", "workflow", "pricing"],
            stop_policy="stop when enough confirmed competitors exist for a useful comparison",
            budget=budget,
        )
        charter = RunCharter(
            mission=f"Produce a competitor map for {target}.",
            scope=["Identify direct competitors", "Capture positioning and pricing"],
            non_goals=["Exhaustive feature-by-feature analysis"],
            success_criteria=["At least 3 confirmed competitors with citations"],
            research_agenda=["Seed candidates", "Validate candidates", "Summarize differences"],
        )
        return brief, charter


class FakeStopJudge:
    """Deterministic test double for stop/continue decisions."""

    def __init__(self, verdict: StopVerdict) -> None:
        self._verdict = verdict

    def run(self, _state: object | None) -> StopDecision:
        reasons = ["Continue: fake stop judge keeps the run going."]
        if self._verdict == StopVerdict.STOP:
            reasons = ["Stop: fake stop judge ends the run."]
        return StopDecision(verdict=self._verdict, reasons=reasons, gap_tickets=[])
