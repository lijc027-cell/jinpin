from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse

from jingyantai.domain.models import FinalReport, RunState
from jingyantai.domain.phases import CandidateStatus

VENDOR_PREFIX_TOKENS = {
    "amazon",
    "anthropic",
    "aws",
    "github",
    "google",
    "meta",
    "microsoft",
    "openai",
}
GENERIC_SUFFIX_TOKENS = {
    "agent",
    "agents",
    "app",
    "apps",
    "assistant",
    "assistants",
    "cli",
    "developer",
    "developers",
    "sdk",
    "tool",
    "tools",
}


def _normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "https").lower()
    domain = parsed.netloc.removeprefix("www.").lower()
    path = parsed.path or ""
    if path in {"", "/"}:
        path = ""
    else:
        path = path.rstrip("/")
    return urlunparse((scheme, domain, path, "", "", ""))


def _ordered_dimensions(state: RunState) -> list[str]:
    finding_dimensions: list[str] = []
    for finding in state.findings:
        if finding.dimension not in finding_dimensions:
            finding_dimensions.append(finding.dimension)

    if state.brief and state.brief.required_dimensions:
        brief_dimensions = list(state.brief.required_dimensions)
        if not finding_dimensions:
            return brief_dimensions
        if any(dimension in brief_dimensions for dimension in finding_dimensions):
            return brief_dimensions
        return finding_dimensions
    return finding_dimensions


def _confidence_band(score: float) -> str:
    if score >= 0.85:
        return "high"
    if score >= 0.65:
        return "medium"
    return "low"


def _normalize_name(name: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", name.lower()))


def _normalize_uncertainty_key(item: object) -> str:
    statement = str(getattr(item, "statement", ""))
    required_evidence = str(getattr(item, "required_evidence", ""))
    return f"{_normalize_name(statement)}|{_normalize_name(required_evidence)}"


def _impact_rank(impact: str) -> int:
    normalized = impact.strip().lower()
    if normalized in {"critical", "high", "could change competitor ranking"}:
        return 0
    if normalized in {"medium", "moderate"}:
        return 1
    return 2


def _resolvability_rank(resolvability: str) -> int:
    normalized = resolvability.strip().lower()
    if normalized in {"easy", "high"}:
        return 0
    if normalized == "medium":
        return 1
    return 2


def _uncertainty_sort_key(item: object) -> tuple[int, int, str]:
    impact = str(getattr(item, "impact", ""))
    resolvability = str(getattr(item, "resolvability", ""))
    statement = str(getattr(item, "statement", ""))
    return (
        _impact_rank(impact),
        _resolvability_rank(resolvability),
        _normalize_name(statement),
    )


def _format_uncertainty(item: object) -> str:
    statement = str(getattr(item, "statement", "")).strip()
    impact = str(getattr(item, "impact", "")).strip().lower() or "unknown"
    resolvability = str(getattr(item, "resolvability", "")).strip().lower() or "unknown"
    required_evidence = str(getattr(item, "required_evidence", "")).strip() or "unknown"
    return (
        f"[{impact}][{resolvability}] {statement}"
        f" | impact: {impact}"
        f" | resolvability: {resolvability}"
        f" | required evidence: {required_evidence}"
    )


def _normalize_name_tokens(name: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", name.lower())


def _trim_generic_suffix_tokens(tokens: list[str]) -> list[str]:
    trimmed = list(tokens)
    while len(trimmed) > 1 and trimmed[-1] in GENERIC_SUFFIX_TOKENS:
        trimmed = trimmed[:-1]
    return trimmed


def _is_informative_variant(tokens: list[str]) -> bool:
    return any(token not in GENERIC_SUFFIX_TOKENS and len(token) > 1 for token in tokens)


def _candidate_company_tokens(candidate: object) -> list[str]:
    company = getattr(candidate, "company", None)
    if not isinstance(company, str):
        return []
    return _normalize_name_tokens(company)


def _candidate_name_variants(candidate: object, raw_name: str) -> set[str]:
    tokens = _normalize_name_tokens(raw_name)
    if not tokens:
        return set()

    variants = {" ".join(tokens)}
    trimmed = _trim_generic_suffix_tokens(tokens)
    if trimmed != tokens and _is_informative_variant(trimmed):
        variants.add(" ".join(trimmed))

    company_tokens = _candidate_company_tokens(candidate)
    if company_tokens and tokens[: len(company_tokens)] == company_tokens and len(tokens) > len(company_tokens):
        stripped_company = tokens[len(company_tokens) :]
        if _is_informative_variant(stripped_company):
            variants.add(" ".join(stripped_company))
            stripped_company_trimmed = _trim_generic_suffix_tokens(stripped_company)
            if _is_informative_variant(stripped_company_trimmed):
                variants.add(" ".join(stripped_company_trimmed))

    if tokens[0] in VENDOR_PREFIX_TOKENS and len(tokens) > 1:
        stripped_vendor = tokens[1:]
        if _is_informative_variant(stripped_vendor):
            variants.add(" ".join(stripped_vendor))
            stripped_vendor_trimmed = _trim_generic_suffix_tokens(stripped_vendor)
            if _is_informative_variant(stripped_vendor_trimmed):
                variants.add(" ".join(stripped_vendor_trimmed))

    return variants


def _candidate_identity_keys(candidate: object) -> set[str]:
    keys: set[str] = set()

    raw_names = [getattr(candidate, "name", "")]
    aliases = getattr(candidate, "aliases", [])
    if isinstance(aliases, list):
        raw_names.extend(alias for alias in aliases if isinstance(alias, str))

    for raw_name in raw_names:
        for variant in _candidate_name_variants(candidate, raw_name):
            keys.add(f"name:{variant}")

    canonical_url = _normalize_url(getattr(candidate, "canonical_url", ""))
    if canonical_url:
        keys.add(f"url:{canonical_url}")
    return keys


def _is_article_like(url: str) -> bool:
    parsed = urlparse(url)
    domain = parsed.netloc.removeprefix("www.").lower()
    segments = [segment.lower() for segment in parsed.path.split("/") if segment]
    if domain in {"taskade.com", "digitalocean.com", "medium.com", "dev.to"}:
        return True
    return bool({"blog", "resources", "articles", "news"} & set(segments))


def _is_repo_or_root_like(url: str) -> bool:
    parsed = urlparse(url)
    domain = parsed.netloc.removeprefix("www.").lower()
    segments = [segment for segment in parsed.path.split("/") if segment]
    if domain == "github.com":
        return len(segments) >= 2
    return len(segments) <= 2


def _citation_source_rank(source_type: str) -> int:
    normalized = source_type.strip().lower()
    if normalized == "official":
        return 0
    if normalized in {"primary", "primary_url"}:
        return 1
    if normalized in {"github", "github_repo"}:
        return 2
    if normalized in {"docs", "documentation"}:
        return 3
    return 4


def _citation_quality_key(*, source_type: str, url: str) -> tuple[int, int, int, str]:
    return (
        _citation_source_rank(source_type),
        1 if _is_article_like(url) else 0,
        0 if _is_repo_or_root_like(url) else 1,
        url,
    )


def _select_citation_urls(candidate: object, group: list, state: RunState) -> list[str]:
    candidate_ids = {item.candidate_id for item in group}
    ranked_urls: dict[str, tuple[int, int, int, str]] = {}
    source_type_by_url: dict[str, str] = {}
    canonical_urls = {
        _normalize_url(getattr(item, "canonical_url", ""))
        for item in [candidate, *group]
        if _normalize_url(getattr(item, "canonical_url", ""))
    }

    for evidence in state.evidence:
        if evidence.subject_id not in candidate_ids or not evidence.source_url.strip():
            continue
        url = _normalize_url(evidence.source_url)
        quality = _citation_quality_key(source_type=evidence.source_type, url=url)
        existing = ranked_urls.get(url)
        if existing is None or quality < existing:
            ranked_urls[url] = quality
            source_type_by_url[url] = str(evidence.source_type)

    urls = list(ranked_urls)
    trusted_non_github_types = {"official", "primary", "primary_url", "docs", "documentation"}
    high_trust_urls = [
        url
        for url in urls
        if source_type_by_url.get(url, "").strip().lower() in trusted_non_github_types or url in canonical_urls
    ]
    if high_trust_urls:
        urls = high_trust_urls

    if any(not _is_article_like(url) for url in urls):
        urls = [url for url in urls if not _is_article_like(url)]

    if not urls:
        canonical_url = _normalize_url(getattr(candidate, "canonical_url", ""))
        if canonical_url:
            urls = [canonical_url]

    return sorted(urls, key=lambda url: ranked_urls.get(url, _citation_quality_key(source_type="", url=url)))


def _candidate_groups(candidates: list) -> list[list]:
    grouped: list[list] = []
    group_keys: list[set[str]] = []
    for candidate in candidates:
        candidate_keys = _candidate_identity_keys(candidate)
        matching_indexes = [
            index
            for index, existing_keys in enumerate(group_keys)
            if candidate_keys & existing_keys
        ]
        if not matching_indexes:
            grouped.append([candidate])
            group_keys.append(set(candidate_keys))
            continue

        primary_index = matching_indexes[0]
        grouped[primary_index].append(candidate)
        group_keys[primary_index].update(candidate_keys)
        for index in reversed(matching_indexes[1:]):
            grouped[primary_index].extend(grouped.pop(index))
            group_keys[primary_index].update(group_keys.pop(index))
    return grouped


def _evidence_counts_by_candidate(state: RunState) -> dict[str, int]:
    counts: dict[str, int] = {}
    for evidence in state.evidence:
        counts[evidence.subject_id] = counts.get(evidence.subject_id, 0) + 1
    return counts


def _findings_counts_by_candidate(state: RunState) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in state.findings:
        counts[finding.subject_id] = counts.get(finding.subject_id, 0) + 1
    return counts


def _select_representative_candidate(group: list, state: RunState):
    evidence_counts = _evidence_counts_by_candidate(state)
    finding_counts = _findings_counts_by_candidate(state)

    def sort_key(candidate):
        candidate_id = candidate.candidate_id
        url = _normalize_url(candidate.canonical_url)
        return (
            0 if finding_counts.get(candidate_id, 0) > 0 else 1,
            0 if evidence_counts.get(candidate_id, 0) > 0 else 1,
            0 if not _is_article_like(url) else 1,
            0 if _is_repo_or_root_like(url) else 1,
            -candidate.relevance_score,
            len(url),
        )

    return min(group, key=sort_key)


def _grouped_candidates(candidates: list, state: RunState) -> list[tuple[object, list]]:
    grouped = _candidate_groups(candidates)
    selected = [(_select_representative_candidate(group, state), group) for group in grouped]
    return sorted(selected, key=lambda item: item[0].relevance_score, reverse=True)


class Synthesizer:
    def run(self, state: RunState) -> FinalReport:
        confirmed_groups = _grouped_candidates(
            [candidate for candidate in state.candidates if candidate.status == CandidateStatus.CONFIRMED],
            state,
        )
        rejected_groups = _grouped_candidates(
            [candidate for candidate in state.candidates if candidate.status == CandidateStatus.REJECTED],
            state,
        )
        dimensions = _ordered_dimensions(state)

        comparison_matrix: list[dict[str, str]] = []
        for candidate, group in confirmed_groups:
            candidate_ids = {item.candidate_id for item in group}
            candidate_findings: dict[str, object] = {}
            for finding in state.findings:
                if finding.subject_id not in candidate_ids:
                    continue
                existing = candidate_findings.get(finding.dimension)
                if existing is None or finding.confidence > existing.confidence:
                    candidate_findings[finding.dimension] = finding
            confidences = [finding.confidence for finding in candidate_findings.values()]
            average_confidence = (
                (sum(confidences) / len(confidences))
                if confidences
                else candidate.relevance_score
            )
            covered_dimensions = sum(1 for dimension in dimensions if dimension in candidate_findings)
            row = {
                "candidate": candidate.name,
                "url": _normalize_url(candidate.canonical_url),
                "confidence": f"{average_confidence:.2f}",
                "confidence_band": _confidence_band(average_confidence),
                "coverage": f"{covered_dimensions}/{len(dimensions)}" if dimensions else "0/0",
            }
            for dimension in dimensions:
                finding = candidate_findings.get(dimension)
                row[dimension] = finding.summary if finding is not None else "Missing direct evidence"
            comparison_matrix.append(row)

        unique_uncertainties: dict[str, object] = {}
        for item in state.uncertainties:
            key = _normalize_uncertainty_key(item)
            existing = unique_uncertainties.get(key)
            if existing is None or _uncertainty_sort_key(item) < _uncertainty_sort_key(existing):
                unique_uncertainties[key] = item

        return FinalReport(
            target_summary=f"Competitive landscape for {state.target}",
            confirmed_competitors=[candidate.name for candidate, _ in confirmed_groups],
            rejected_candidates=[candidate.name for candidate, _ in rejected_groups],
            comparison_matrix=comparison_matrix,
            key_uncertainties=[
                _format_uncertainty(item)
                for item in sorted(unique_uncertainties.values(), key=_uncertainty_sort_key)
            ],
            citations={},
        )


class CitationAgent:
    def run(self, state: RunState, draft: FinalReport) -> FinalReport:
        citations: dict[str, list[str]] = {}
        for candidate, group in _grouped_candidates(
            [item for item in state.candidates if item.status == CandidateStatus.CONFIRMED],
            state,
        ):
            citations[candidate.name] = _select_citation_urls(candidate, group, state)
        return draft.model_copy(update={"citations": citations})
