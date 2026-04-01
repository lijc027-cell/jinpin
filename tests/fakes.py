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
            product_type="coding-agent",
            competitor_definition="Terminal-based coding agents",
            required_dimensions=["positioning", "workflow", "pricing"],
            stop_policy="stop when confidence is high",
            budget=budget,
        )
        charter = RunCharter(
            mission=f"Competitive research charter for {target}.",
            scope=["positioning", "github", "heat", "workflow", "pricing"],
            non_goals=["Deep product teardown", "Hands-on benchmarking"],
            success_criteria=["A defensible competitor set with cited evidence"],
            research_agenda=["Discover candidates", "Collect evidence", "Synthesize comparison"],
        )
        return brief, charter


class FakeStopJudge:
    """Deterministic test double for stop/continue decisions."""

    def __init__(self, verdict: StopVerdict) -> None:
        self._verdict = verdict

    def run(self, _state: object | None) -> StopDecision:
        return StopDecision(verdict=self._verdict, reasons=["test verdict"], gap_tickets=[])
