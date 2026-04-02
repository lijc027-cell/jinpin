from __future__ import annotations

from pydantic import BaseModel, Field


class InitializerOutput(BaseModel):
    brief_target: str
    product_type: str
    competitor_definition: str
    required_dimensions: list[str]
    stop_policy: str
    charter_mission: str
    charter_scope: list[str]
    charter_non_goals: list[str]
    charter_success_criteria: list[str]
    charter_research_agenda: list[str]


class LeadResearcherOutput(BaseModel):
    round_plan: str
    focus_targets: list[str] = Field(default_factory=list)
    why_this_round: str = ""


class ScoutCandidateDraft(BaseModel):
    name: str
    canonical_url: str
    why_candidate: str
    company: str | None = None
    aliases: list[str] = Field(default_factory=list)
    suggested_relevance: float = 0.75


class ScoutOutput(BaseModel):
    candidates: list[ScoutCandidateDraft] = Field(default_factory=list)


class EvidenceDraft(BaseModel):
    claim: str
    source_url: str
    source_type: str
    snippet: str
    supports_or_conflicts: str = "supports"
    confidence: float = 0.75
    freshness_score: float = 0.8


class FindingDraft(BaseModel):
    dimension: str
    summary: str
    evidence_refs: list[int]
    confidence: float = 0.75


class UncertaintyDraft(BaseModel):
    statement: str
    impact: str
    resolvability: str
    required_evidence: str


class AnalystOutput(BaseModel):
    evidence: list[EvidenceDraft] = Field(default_factory=list)
    findings: list[FindingDraft] = Field(default_factory=list)
    uncertainties: list[UncertaintyDraft] = Field(default_factory=list)
