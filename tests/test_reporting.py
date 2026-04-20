from __future__ import annotations

from jingyantai.domain.models import BudgetPolicy, Candidate, Evidence, Finding, ResearchBrief, RunState, UncertaintyItem
from jingyantai.domain.phases import CandidateStatus, Phase
from jingyantai.runtime.reporting import CitationAgent, Synthesizer


def _state() -> RunState:
    return RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.STOP,
        budget=BudgetPolicy(
            max_rounds=4,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        ),
    )


def test_synthesizer_and_citation_agent_build_cited_report():
    state = _state()
    state.candidates.append(
        Candidate(
            candidate_id="a",
            name="Aider",
            canonical_url="https://aider.chat",
            status=CandidateStatus.CONFIRMED,
            relevance_score=0.93,
            why_candidate="terminal coding agent",
        )
    )
    state.evidence.append(
        Evidence(
            evidence_id="e1",
            subject_id="a",
            claim="Aider runs in the terminal",
            source_url="https://aider.chat",
            source_type="official",
            snippet="AI pair programmer in your terminal",
            captured_at="2026-04-01",
            freshness_score=0.95,
            confidence=0.95,
        )
    )
    state.findings.append(
        Finding(
            finding_id="f1",
            subject_id="a",
            dimension="workflow",
            summary="Aider overlaps with Claude Code in terminal workflow.",
            evidence_ids=["e1"],
            confidence=0.95,
        )
    )

    draft = Synthesizer().run(state)
    final = CitationAgent().run(state, draft)

    assert final.confirmed_competitors == ["Aider"]
    assert final.citations["Aider"] == ["https://aider.chat"]


def test_synthesizer_builds_dimension_matrix_and_formats_uncertainties():
    state = _state()
    state.candidates.append(
        Candidate(
            candidate_id="a",
            name="Aider",
            canonical_url="https://aider.chat/",
            status=CandidateStatus.CONFIRMED,
            relevance_score=0.93,
            why_candidate="terminal coding agent",
        )
    )
    state.findings.extend(
        [
            Finding(
                finding_id="f-positioning",
                subject_id="a",
                dimension="positioning",
                summary="Terminal-native coding agent.",
                evidence_ids=["e1"],
                confidence=0.90,
            ),
            Finding(
                finding_id="f-workflow",
                subject_id="a",
                dimension="workflow",
                summary="Works directly in local repos.",
                evidence_ids=["e2"],
                confidence=0.92,
            ),
            Finding(
                finding_id="f-pricing",
                subject_id="a",
                dimension="pricing or access",
                summary="Open-source core with API costs.",
                evidence_ids=["e3"],
                confidence=0.88,
            ),
        ]
    )
    state.uncertainties.append(
        UncertaintyItem(
            statement="Enterprise seat pricing is unclear.",
            impact="high",
            resolvability="medium",
            required_evidence="official pricing page",
            owner_role="analyst_pricing",
        )
    )

    draft = Synthesizer().run(state)
    row = draft.comparison_matrix[0]

    assert row["candidate"] == "Aider"
    assert row["url"] == "https://aider.chat"
    assert row["positioning"] == "Terminal-native coding agent."
    assert row["workflow"] == "Works directly in local repos."
    assert row["pricing or access"] == "Open-source core with API costs."
    assert row["confidence"] == "0.90"
    assert "impact: high" in draft.key_uncertainties[0]
    assert "required evidence: official pricing page" in draft.key_uncertainties[0]


def test_citation_agent_dedupes_blank_and_duplicate_urls():
    state = _state()
    state.candidates.append(
        Candidate(
            candidate_id="a",
            name="Aider",
            canonical_url="https://aider.chat",
            status=CandidateStatus.CONFIRMED,
            relevance_score=0.93,
            why_candidate="terminal coding agent",
        )
    )
    state.evidence.extend(
        [
            Evidence(
                evidence_id="e1",
                subject_id="a",
                claim="claim",
                source_url="https://aider.chat/",
                source_type="official",
                snippet="snippet",
                captured_at="2026-04-01",
                freshness_score=0.95,
                confidence=0.95,
            ),
            Evidence(
                evidence_id="e2",
                subject_id="a",
                claim="claim",
                source_url="https://aider.chat",
                source_type="official",
                snippet="snippet",
                captured_at="2026-04-01",
                freshness_score=0.95,
                confidence=0.95,
            ),
            Evidence(
                evidence_id="e3",
                subject_id="a",
                claim="claim",
                source_url="",
                source_type="official",
                snippet="snippet",
                captured_at="2026-04-01",
                freshness_score=0.95,
                confidence=0.95,
            ),
        ]
    )

    draft = Synthesizer().run(state)
    final = CitationAgent().run(state, draft)

    assert final.citations["Aider"] == ["https://aider.chat"]


def test_synthesizer_merges_duplicate_candidate_names_and_prefers_non_article_representative():
    state = _state()
    state.candidates.extend(
        [
            Candidate(
                candidate_id="gemini-article",
                name="Gemini CLI",
                canonical_url="https://taskade.com/blog/claude-code-alternatives/",
                status=CandidateStatus.CONFIRMED,
                relevance_score=0.97,
                why_candidate="terminal coding agent",
            ),
            Candidate(
                candidate_id="gemini-github",
                name="Gemini CLI",
                canonical_url="https://github.com/google/gemini-cli",
                status=CandidateStatus.CONFIRMED,
                relevance_score=0.85,
                why_candidate="terminal coding agent",
            ),
        ]
    )
    state.findings.append(
        Finding(
            finding_id="f-gemini-workflow",
            subject_id="gemini-github",
            dimension="workflow",
            summary="Runs coding flows from a GitHub-backed CLI project.",
            evidence_ids=["e-gemini-1"],
            confidence=0.91,
        )
    )

    draft = Synthesizer().run(state)

    assert draft.confirmed_competitors == ["Gemini CLI"]
    assert len(draft.comparison_matrix) == 1
    row = draft.comparison_matrix[0]
    assert row["url"] == "https://github.com/google/gemini-cli"
    assert row["workflow"] == "Runs coding flows from a GitHub-backed CLI project."


def test_citation_agent_merges_duplicate_name_groups_and_falls_back_to_canonical_url():
    state = _state()
    state.candidates.extend(
        [
            Candidate(
                candidate_id="aider-github",
                name="Aider",
                canonical_url="https://github.com/paul-gauthier/aider",
                status=CandidateStatus.CONFIRMED,
                relevance_score=0.93,
                why_candidate="terminal coding agent",
            ),
            Candidate(
                candidate_id="aider-site",
                name="Aider",
                canonical_url="https://aider.chat",
                status=CandidateStatus.CONFIRMED,
                relevance_score=0.90,
                why_candidate="terminal coding agent",
            ),
            Candidate(
                candidate_id="cursor",
                name="Cursor",
                canonical_url="https://cursor.sh/",
                status=CandidateStatus.CONFIRMED,
                relevance_score=0.89,
                why_candidate="editor competitor",
            ),
        ]
    )
    state.evidence.extend(
        [
            Evidence(
                evidence_id="e1",
                subject_id="aider-github",
                claim="claim",
                source_url="https://github.com/paul-gauthier/aider",
                source_type="official",
                snippet="snippet",
                captured_at="2026-04-01",
                freshness_score=0.95,
                confidence=0.95,
            ),
            Evidence(
                evidence_id="e2",
                subject_id="aider-site",
                claim="claim",
                source_url="https://aider.chat/",
                source_type="official",
                snippet="snippet",
                captured_at="2026-04-01",
                freshness_score=0.95,
                confidence=0.95,
            ),
        ]
    )

    draft = Synthesizer().run(state)
    final = CitationAgent().run(state, draft)

    assert final.citations["Aider"] == [
        "https://aider.chat",
        "https://github.com/paul-gauthier/aider",
    ]
    assert final.citations["Cursor"] == ["https://cursor.sh"]


def test_reporting_merges_brand_prefixed_and_suffix_variants_into_one_entity():
    state = _state()
    state.candidates.extend(
        [
            Candidate(
                candidate_id="codex-site",
                name="OpenAI Codex",
                canonical_url="https://openai.com/index/codex/",
                status=CandidateStatus.CONFIRMED,
                relevance_score=0.93,
                why_candidate="terminal coding agent",
            ),
            Candidate(
                candidate_id="codex-github",
                name="Codex CLI",
                canonical_url="https://github.com/openai/codex",
                status=CandidateStatus.CONFIRMED,
                relevance_score=0.89,
                why_candidate="repo-aware coding agent",
            ),
        ]
    )
    state.findings.extend(
        [
            Finding(
                finding_id="f-codex-positioning",
                subject_id="codex-site",
                dimension="positioning",
                summary="OpenAI's coding agent for software engineering tasks.",
                evidence_ids=["e-codex-site"],
                confidence=0.95,
            ),
            Finding(
                finding_id="f-codex-workflow",
                subject_id="codex-github",
                dimension="workflow",
                summary="Exposed through a repo-backed CLI workflow.",
                evidence_ids=["e-codex-github"],
                confidence=0.91,
            ),
        ]
    )
    state.evidence.extend(
        [
            Evidence(
                evidence_id="e-codex-site",
                subject_id="codex-site",
                claim="OpenAI Codex product page",
                source_url="https://openai.com/index/codex/",
                source_type="official",
                snippet="Codex is OpenAI's software engineering agent.",
                captured_at="2026-04-02",
                freshness_score=0.96,
                confidence=0.95,
            ),
            Evidence(
                evidence_id="e-codex-github",
                subject_id="codex-github",
                claim="Codex CLI repository",
                source_url="https://github.com/openai/codex",
                source_type="github",
                snippet="CLI and workflow documentation.",
                captured_at="2026-04-02",
                freshness_score=0.94,
                confidence=0.91,
            ),
        ]
    )

    draft = Synthesizer().run(state)
    final = CitationAgent().run(state, draft)

    assert draft.confirmed_competitors == ["OpenAI Codex"]
    assert len(draft.comparison_matrix) == 1
    row = draft.comparison_matrix[0]
    assert row["positioning"] == "OpenAI's coding agent for software engineering tasks."
    assert row["workflow"] == "Exposed through a repo-backed CLI workflow."
    assert final.citations["OpenAI Codex"] == [
        "https://openai.com/index/codex",
        "https://github.com/openai/codex",
    ]


def test_citation_agent_prefers_official_and_repo_urls_over_article_like_sources():
    state = _state()
    state.candidates.append(
        Candidate(
            candidate_id="gemini",
            name="Gemini CLI",
            canonical_url="https://github.com/google/gemini-cli",
            status=CandidateStatus.CONFIRMED,
            relevance_score=0.9,
            why_candidate="terminal coding agent",
        )
    )
    state.evidence.extend(
        [
            Evidence(
                evidence_id="e-article",
                subject_id="gemini",
                claim="article mention",
                source_url="https://taskade.com/blog/claude-code-alternatives/",
                source_type="web",
                snippet="article",
                captured_at="2026-04-01",
                freshness_score=0.8,
                confidence=0.7,
            ),
            Evidence(
                evidence_id="e-github",
                subject_id="gemini",
                claim="repo",
                source_url="https://github.com/google/gemini-cli",
                source_type="github",
                snippet="repo",
                captured_at="2026-04-01",
                freshness_score=0.95,
                confidence=0.95,
            ),
            Evidence(
                evidence_id="e-official",
                subject_id="gemini",
                claim="docs",
                source_url="https://ai.google.dev/gemini-api/docs/cli",
                source_type="official",
                snippet="official docs",
                captured_at="2026-04-01",
                freshness_score=0.95,
                confidence=0.95,
            ),
        ]
    )

    final = CitationAgent().run(state, Synthesizer().run(state))

    assert final.citations["Gemini CLI"] == [
        "https://ai.google.dev/gemini-api/docs/cli",
        "https://github.com/google/gemini-cli",
    ]


def test_synthesizer_adds_coverage_and_confidence_band_to_matrix():
    state = _state()
    state.brief = ResearchBrief(
        target="Claude Code",
        product_type="coding-agent",
        competitor_definition="Direct competitors are terminal-native coding agents.",
        required_dimensions=["positioning", "workflow", "pricing or access"],
        stop_policy="Stop when coverage is enough.",
        budget=state.budget,
    )
    state.candidates.append(
        Candidate(
            candidate_id="a",
            name="Aider",
            canonical_url="https://aider.chat",
            status=CandidateStatus.CONFIRMED,
            relevance_score=0.93,
            why_candidate="terminal coding agent",
        )
    )
    state.findings.extend(
        [
            Finding(
                finding_id="f-positioning",
                subject_id="a",
                dimension="positioning",
                summary="Terminal-native coding agent.",
                evidence_ids=["e1"],
                confidence=0.90,
            ),
            Finding(
                finding_id="f-workflow",
                subject_id="a",
                dimension="workflow",
                summary="Works directly in local repos.",
                evidence_ids=["e2"],
                confidence=0.92,
            ),
        ]
    )

    row = Synthesizer().run(state).comparison_matrix[0]

    assert row["coverage"] == "2/3"
    assert row["confidence_band"] == "high"


def test_synthesizer_marks_missing_dimensions_explicitly():
    state = _state()
    state.brief = ResearchBrief(
        target="Claude Code",
        product_type="coding-agent",
        competitor_definition="Direct competitors are terminal-native coding agents.",
        required_dimensions=["workflow", "pricing or access"],
        stop_policy="Stop when coverage is enough.",
        budget=state.budget,
    )
    state.candidates.append(
        Candidate(
            candidate_id="a",
            name="Aider",
            canonical_url="https://aider.chat",
            status=CandidateStatus.CONFIRMED,
            relevance_score=0.93,
            why_candidate="terminal coding agent",
        )
    )
    state.findings.append(
        Finding(
            finding_id="f-workflow",
            subject_id="a",
            dimension="workflow",
            summary="Works directly in local repos.",
            evidence_ids=["e1"],
            confidence=0.92,
        )
    )

    row = Synthesizer().run(state).comparison_matrix[0]

    assert row["pricing or access"] == "Missing direct evidence"


def test_synthesizer_sorts_and_formats_uncertainties_by_priority():
    state = _state()
    state.uncertainties.extend(
        [
            UncertaintyItem(
                statement="Low-priority workflow edge case remains unclear.",
                impact="low",
                resolvability="hard",
                required_evidence="community issue thread",
                owner_role="analyst_workflow",
            ),
            UncertaintyItem(
                statement="Enterprise pricing remains unclear.",
                impact="high",
                resolvability="medium",
                required_evidence="official pricing page",
                owner_role="analyst_pricing",
            ),
        ]
    )

    items = Synthesizer().run(state).key_uncertainties

    assert items[0].startswith("[high][medium] Enterprise pricing remains unclear.")
    assert "required evidence: official pricing page" in items[0]
    assert items[1].startswith("[low][hard] Low-priority workflow edge case remains unclear.")


def test_synthesizer_dedupes_equivalent_uncertainties():
    state = _state()
    state.uncertainties.extend(
        [
            UncertaintyItem(
                statement="Enterprise pricing remains unclear.",
                impact="high",
                resolvability="medium",
                required_evidence="official pricing page",
                owner_role="analyst_pricing",
            ),
            UncertaintyItem(
                statement="enterprise pricing remains unclear",
                impact="high",
                resolvability="medium",
                required_evidence="official pricing page",
                owner_role="analyst_pricing",
            ),
        ]
    )

    items = Synthesizer().run(state).key_uncertainties

    assert len(items) == 1


def test_synthesizer_falls_back_to_finding_dimensions_when_brief_dimensions_do_not_overlap():
    state = _state()
    state.brief = ResearchBrief(
        target="Claude Code",
        product_type="coding-agent",
        competitor_definition="Direct competitors are terminal-native coding agents.",
        required_dimensions=[
            "code generation quality",
            "programming language support",
        ],
        stop_policy="Stop when coverage is enough.",
        budget=state.budget,
    )
    state.candidates.append(
        Candidate(
            candidate_id="a",
            name="Aider",
            canonical_url="https://aider.chat",
            status=CandidateStatus.CONFIRMED,
            relevance_score=0.93,
            why_candidate="terminal coding agent",
        )
    )
    state.findings.append(
        Finding(
            finding_id="f-positioning",
            subject_id="a",
            dimension="positioning",
            summary="Terminal-native coding agent.",
            evidence_ids=["e1"],
            confidence=0.90,
        )
    )

    row = Synthesizer().run(state).comparison_matrix[0]

    assert row["coverage"] == "1/1"
    assert row["positioning"] == "Terminal-native coding agent."
    assert "code generation quality" not in row


def test_citation_agent_prefers_group_canonical_and_official_urls_over_generic_or_unrelated_github_sources():
    state = _state()
    state.candidates.extend(
        [
            Candidate(
                candidate_id="open-code",
                name="OpenCode",
                canonical_url="https://github.com/opencode-ai/opencode",
                status=CandidateStatus.CONFIRMED,
                relevance_score=0.9,
                why_candidate="terminal coding agent",
            ),
            Candidate(
                candidate_id="open-code-site",
                name="OpenCode",
                canonical_url="https://opencode.ai",
                status=CandidateStatus.CONFIRMED,
                relevance_score=0.88,
                why_candidate="terminal coding agent",
            ),
        ]
    )
    state.evidence.extend(
        [
            Evidence(
                evidence_id="e-primary",
                subject_id="open-code",
                claim="primary repo",
                source_url="https://github.com/opencode-ai/opencode",
                source_type="primary_url",
                snippet="repo",
                captured_at="2026-04-01",
                freshness_score=0.95,
                confidence=0.95,
            ),
            Evidence(
                evidence_id="e-official",
                subject_id="open-code",
                claim="official site",
                source_url="https://opencode.ai",
                source_type="official",
                snippet="site",
                captured_at="2026-04-01",
                freshness_score=0.95,
                confidence=0.95,
            ),
            Evidence(
                evidence_id="e-unrelated-github",
                subject_id="open-code",
                claim="unrelated repo",
                source_url="https://github.com/farion1231/cc-switch",
                source_type="github",
                snippet="repo",
                captured_at="2026-04-01",
                freshness_score=0.8,
                confidence=0.7,
            ),
            Evidence(
                evidence_id="e-web",
                subject_id="open-code",
                claim="generic web page",
                source_url="https://agentwiki.org/opencode",
                source_type="web_page",
                snippet="wiki",
                captured_at="2026-04-01",
                freshness_score=0.8,
                confidence=0.7,
            ),
        ]
    )

    final = CitationAgent().run(state, Synthesizer().run(state))

    assert final.citations["OpenCode"] == [
        "https://opencode.ai",
        "https://github.com/opencode-ai/opencode",
    ]
