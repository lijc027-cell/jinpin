from __future__ import annotations

from jingyantai.domain.models import BudgetPolicy, ResearchBrief, RunCharter, RunState, StopDecision
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
            competitor_definition="Direct competitors are terminal-native coding agents for software engineers.",
            required_dimensions=[
                "positioning",
                "workflow",
                "core capabilities",
                "pricing or access",
                "community / ecosystem signal",
            ],
            stop_policy="Stop after enough confirmed competitors with coverage.",
            budget=budget,
        )
        charter = RunCharter(
            mission=f"Research competitors for {target}",
            scope=["direct competitors", "terminal coding agents"],
            non_goals=["broad LLM platform analysis"],
            success_criteria=["3 confirmed competitors", "all required dimensions covered"],
            research_agenda=["expand", "deepen", "challenge"],
        )
        return brief, charter


class FakeStopJudge:
    """Deterministic test double for stop/continue decisions."""

    def __init__(self, verdict: StopVerdict) -> None:
        self._verdict = verdict

    def run(self, state: RunState) -> StopDecision:
        return StopDecision(verdict=self._verdict, reasons=["test verdict"], gap_tickets=[])
