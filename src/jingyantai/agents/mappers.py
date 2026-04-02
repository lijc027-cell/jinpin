from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse

from jingyantai.agents.schemas import AnalystOutput, InitializerOutput, ScoutOutput
from jingyantai.domain.models import (
    BudgetPolicy,
    Candidate,
    Evidence,
    Finding,
    ResearchBrief,
    RunCharter,
    UncertaintyItem,
)
from jingyantai.domain.phases import CandidateStatus


def _slug(value: str) -> str:
    chars: list[str] = []
    last_dash = False
    for char in value.lower():
        if char.isalnum():
            chars.append(char)
            last_dash = False
        elif not last_dash:
            chars.append("-")
            last_dash = True
    return "".join(chars).strip("-") or "item"


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


class InitializerMapper:
    def map(self, output: InitializerOutput, budget: BudgetPolicy) -> tuple[ResearchBrief, RunCharter]:
        brief = ResearchBrief(
            target=output.brief_target,
            product_type=output.product_type,
            competitor_definition=output.competitor_definition,
            required_dimensions=output.required_dimensions,
            stop_policy=output.stop_policy,
            budget=budget,
        )
        charter = RunCharter(
            mission=output.charter_mission,
            scope=output.charter_scope,
            non_goals=output.charter_non_goals,
            success_criteria=output.charter_success_criteria,
            research_agenda=output.charter_research_agenda,
        )
        return brief, charter


class ScoutMapper:
    def map(self, output: ScoutOutput) -> list[Candidate]:
        seen: dict[str, int] = {}
        candidates: list[Candidate] = []
        for draft in output.candidates:
            base_slug = _slug(draft.name)
            host = urlparse(draft.canonical_url).netloc.replace("www.", "")
            if host:
                base_slug = f"{base_slug}-{_slug(host)}"
            seen[base_slug] = seen.get(base_slug, 0) + 1
            suffix = seen[base_slug]
            candidate_id = f"cand-{base_slug}" if suffix == 1 else f"cand-{base_slug}-{suffix}"
            candidates.append(
                Candidate(
                    candidate_id=candidate_id,
                    name=draft.name,
                    canonical_url=draft.canonical_url,
                    status=CandidateStatus.DISCOVERED,
                    relevance_score=_clamp(draft.suggested_relevance),
                    why_candidate=draft.why_candidate,
                    aliases=draft.aliases,
                    company=draft.company,
                )
            )
        return candidates


class AnalystMapper:
    def map(
        self, candidate: Candidate, dimension: str, output: AnalystOutput
    ) -> tuple[list[Evidence], list[Finding], list[UncertaintyItem]]:
        captured_at = datetime.now(UTC).date().isoformat()
        dimension_slug = _slug(dimension)

        evidence: list[Evidence] = []
        for index, draft in enumerate(output.evidence, start=1):
            evidence.append(
                Evidence(
                    evidence_id=f"e-{candidate.candidate_id}-{dimension_slug}-{index}",
                    subject_id=candidate.candidate_id,
                    claim=draft.claim,
                    source_url=draft.source_url,
                    source_type=draft.source_type,
                    snippet=draft.snippet,
                    captured_at=captured_at,
                    freshness_score=_clamp(draft.freshness_score),
                    confidence=_clamp(draft.confidence),
                    supports_or_conflicts=draft.supports_or_conflicts,
                )
            )

        findings: list[Finding] = []
        for index, draft in enumerate(output.findings, start=1):
            evidence_ids: list[str] = []
            for ref in draft.evidence_refs:
                if ref < 0 or ref >= len(evidence):
                    raise ValueError(f"Invalid evidence reference: {ref}")
                evidence_ids.append(evidence[ref].evidence_id)
            findings.append(
                Finding(
                    finding_id=f"f-{candidate.candidate_id}-{dimension_slug}-{index}",
                    subject_id=candidate.candidate_id,
                    dimension=draft.dimension,
                    summary=draft.summary,
                    evidence_ids=evidence_ids,
                    confidence=_clamp(draft.confidence),
                )
            )

        uncertainties = [
            UncertaintyItem(
                statement=draft.statement,
                impact=draft.impact,
                resolvability=draft.resolvability,
                required_evidence=draft.required_evidence,
                owner_role="analyst",
            )
            for draft in output.uncertainties
        ]

        return evidence, findings, uncertainties
