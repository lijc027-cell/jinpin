from __future__ import annotations

from typing import Protocol

from jingyantai.domain.models import (
    Candidate,
    Evidence,
    Finding,
    GapTicket,
    ResearchBrief,
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
    def run(self, state: RunState) -> list[GapTicket]: ...


class StopJudgeAgent(Protocol):
    def run(self, state: RunState | None) -> StopDecision: ...


class SynthesizerAgent(Protocol):
    def run(self, state: RunState) -> str: ...


class CitationAgent(Protocol):
    def run(self, report: str, evidence: list[Evidence]) -> str: ...
