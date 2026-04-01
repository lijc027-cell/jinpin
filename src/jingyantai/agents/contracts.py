from __future__ import annotations

from typing import Protocol

from jingyantai.domain.models import (
    Candidate,
    Evidence,
    Finding,
    GapTicket,
    FinalReport,
    ResearchBrief,
    ReviewDecision,
    RunCharter,
    RunState,
    StopDecision,
    UncertaintyItem,
)


class InitializerAgent(Protocol):
    def run(self, target: str) -> tuple[ResearchBrief, RunCharter]: ...


class LeadResearcherAgent(Protocol):
    def run(self, state: RunState) -> str: ...


class ScoutAgent(Protocol):
    def run(self, state: RunState) -> list[Candidate]: ...


class AnalystAgent(Protocol):
    def run(
        self, state: RunState, candidate: Candidate
    ) -> tuple[list[Evidence], list[Finding], list[UncertaintyItem]]: ...


class JudgeAgent(Protocol):
    def run(self, state: RunState) -> ReviewDecision: ...


class StopJudgeAgent(Protocol):
    def run(self, state: RunState) -> StopDecision: ...


class SynthesizerAgent(Protocol):
    def run(self, state: RunState) -> FinalReport: ...


class CitationAgent(Protocol):
    def run(self, state: RunState, draft: FinalReport) -> FinalReport: ...
