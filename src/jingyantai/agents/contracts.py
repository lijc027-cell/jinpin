from __future__ import annotations

from typing import Protocol

from jingyantai.domain.models import (
    Candidate,
    FinalReport,
    Finding,
    ResearchBrief,
    ReviewDecision,
    RunCharter,
    RunState,
    StopDecision,
)


class InitializerAgent(Protocol):
    def run(self, target: str) -> tuple[ResearchBrief, RunCharter]: ...


class LeadResearcherAgent(Protocol):
    def run(self, state: RunState) -> str: ...


class ScoutAgent(Protocol):
    def run(self, state: RunState) -> list[Candidate]: ...


class AnalystAgent(Protocol):
    def run(self, state: RunState) -> list[Finding]: ...


class JudgeAgent(Protocol):
    def run(self, state: RunState) -> list[ReviewDecision]: ...


class StopJudgeAgent(Protocol):
    def run(self, state: RunState | None) -> StopDecision: ...


class SynthesizerAgent(Protocol):
    def run(self, state: RunState) -> FinalReport: ...


class CitationAgent(Protocol):
    def run(self, report: FinalReport) -> FinalReport: ...
