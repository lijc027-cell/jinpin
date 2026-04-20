from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class CalibrationVerdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    EDGE_CASE = "edge_case"


class CalibrationRoleScope(StrEnum):
    ALL = "all"
    LEAD_RESEARCHER = "lead_researcher"
    SCOUT = "scout"
    ANALYST = "analyst"
    JUDGE = "judge"


class CalibrationExample(BaseModel):
    role_scope: CalibrationRoleScope
    verdict: CalibrationVerdict
    example: str = Field(..., min_length=1)
    lesson: str = Field(..., min_length=1)


def _default_calibration_examples() -> list[CalibrationExample]:
    return [
        CalibrationExample(
            role_scope=CalibrationRoleScope.LEAD_RESEARCHER,
            verdict=CalibrationVerdict.PASS,
            example="Use one goal cluster to close a named pricing gap for a confirmed candidate.",
            lesson="Keep the round plan narrow, auditable, and tied to one bottleneck.",
        ),
        CalibrationExample(
            role_scope=CalibrationRoleScope.LEAD_RESEARCHER,
            verdict=CalibrationVerdict.FAIL,
            example="Restate the whole mission and ask every scout and analyst to search broadly again.",
            lesson="Avoid broad restarts when gap_tickets already identify the constraint.",
        ),
        CalibrationExample(
            role_scope=CalibrationRoleScope.LEAD_RESEARCHER,
            verdict=CalibrationVerdict.EDGE_CASE,
            example="Revisit a watchlist entity only when the trigger suggests fresh evidence can close the current gap.",
            lesson="A revisit is valid when it materially reduces uncertainty, not just because the entity exists.",
        ),
        CalibrationExample(
            role_scope=CalibrationRoleScope.SCOUT,
            verdict=CalibrationVerdict.PASS,
            example="Keep the canonical product URL or official repo that directly overlaps with the target workflow.",
            lesson="Prefer the candidate that can close required dimensions with direct product evidence.",
        ),
        CalibrationExample(
            role_scope=CalibrationRoleScope.SCOUT,
            verdict=CalibrationVerdict.FAIL,
            example="Promote a blog post, agency, or generic AI toolkit with no product overlap.",
            lesson="Content and service pages are not competitors unless they resolve to a real overlapping product.",
        ),
        CalibrationExample(
            role_scope=CalibrationRoleScope.SCOUT,
            verdict=CalibrationVerdict.EDGE_CASE,
            example="Keep one repo-first candidate when the official site is weak but GitHub activity is fresh and product-specific.",
            lesson="Repo fallback is acceptable when it materially improves canonical evidence quality.",
        ),
        CalibrationExample(
            role_scope=CalibrationRoleScope.ANALYST,
            verdict=CalibrationVerdict.PASS,
            example="Create one finding only after citing bundle-backed evidence with concrete evidence_refs.",
            lesson="Evidence should lead findings, not the other way around.",
        ),
        CalibrationExample(
            role_scope=CalibrationRoleScope.ANALYST,
            verdict=CalibrationVerdict.FAIL,
            example="Infer pricing tiers, workflow steps, or positioning claims without direct support in the bundle.",
            lesson="If the bundle cannot support the claim, emit uncertainty instead of guessing.",
        ),
        CalibrationExample(
            role_scope=CalibrationRoleScope.ANALYST,
            verdict=CalibrationVerdict.EDGE_CASE,
            example="Use a GitHub or fallback page only when the primary page is blocked and the source clearly reduces a named uncertainty.",
            lesson="Fallback evidence is acceptable when it is explicit, auditable, and better than silence.",
        ),
    ]


class QualityRubric(BaseModel):
    direct_competitor_definition: str = Field(
        default="Direct competitors are terminal-native coding agents for software engineers."
    )
    evidence_freshness_threshold: float = Field(0.2, ge=0.0, le=1.0)
    evidence_confidence_threshold: float = Field(0.6, ge=0.0, le=1.0)
    required_dimensions: list[str] = Field(
        default_factory=lambda: ["positioning", "workflow", "pricing or access"]
    )
    high_impact_uncertainty_impacts: list[str] = Field(
        default_factory=lambda: ["high", "critical", "could change competitor ranking"]
    )
    rejection_rules: list[str] = Field(
        default_factory=lambda: [
            "single_goal_cluster",
            "require_hard_checks",
            "concrete_done_definition",
        ]
    )
    calibration_examples: list[CalibrationExample] = Field(default_factory=_default_calibration_examples)

    @classmethod
    def default(cls) -> "QualityRubric":
        return cls()
