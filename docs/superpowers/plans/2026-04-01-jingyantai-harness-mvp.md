# 竞研台 Harness MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first working version of `竞研台`, a long-running competitive research harness for small teams, focused on researching `Claude Code` competitors with explicit generator/evaluator separation.

**Architecture:** The MVP is a Python package with a file-backed run store, a phase-driven harness controller, protocol-separated generator and evaluator agents, a task-level research tool layer, and a CLI entrypoint. The runtime loops through initialize, expand, converge, deepen, challenge, and decide phases until the `Stop Judge` returns `STOP` or the circuit breaker trips, then emits a cited final report.

**Tech Stack:** Python 3.12, Pydantic v2, Typer, Rich, httpx, BeautifulSoup, deepagents adapter, pytest

---

> 2026-04-02 补充说明：本文件仍然是 `竞研台` 的原始基线计划。真实 LLM 接入、搜索 provider 替换、联调稳定化任务，以及与当前实现存在偏差的地方，统一由 `docs/superpowers/plans/2026-04-02-jingyantai-llm-runtime.md` 做增量覆盖；未冲突部分继续以本文件为准。

## Project Root

All files in this plan live under:

`/Users/l/Downloads/projects/竞品`

## File Structure

- `pyproject.toml`
  Package metadata, dependencies, test config, CLI entrypoint.
- `.gitignore`
  Ignore virtualenvs, cache files, run artifacts, local secrets.
- `.env.example`
  Example runtime configuration for model and tool providers.
- `README.md`
  Project overview, setup, and local run instructions.
- `src/jingyantai/__init__.py`
  Package version and public export marker.
- `src/jingyantai/config.py`
  Pydantic settings for model provider, Tavily key, GitHub token, run directory.
- `src/jingyantai/cli.py`
  Typer-based CLI to launch runs and inspect artifacts.
- `src/jingyantai/domain/phases.py`
  Runtime enums for phases, candidate state, verdicts, and priorities.
- `src/jingyantai/domain/models.py`
  Structured runtime models such as `ResearchBrief`, `Candidate`, `Evidence`, `GapTicket`, `RunState`, and `FinalReport`.
- `src/jingyantai/storage/run_store.py`
  File-backed persistence for run state, traces, evidence packs, and reports.
- `src/jingyantai/tools/contracts.py`
  Agent-facing research tool protocol.
- `src/jingyantai/tools/web_search.py`
  Web search client for candidate expansion queries.
- `src/jingyantai/tools/page_extract.py`
  Web page fetch and text extraction helper.
- `src/jingyantai/tools/github_signals.py`
  GitHub search and repository activity signal client.
- `src/jingyantai/tools/research_tools.py`
  Task-level research tool implementation that agents call.
- `src/jingyantai/agents/contracts.py`
  Protocols and payload/result models for initializer, lead researcher, scouts, analysts, judges, and report roles.
- `src/jingyantai/agents/prompts.py`
  System prompts for each role.
- `src/jingyantai/agents/deepagents_adapter.py`
  Adapter that runs role prompts and parses JSON payloads through deepagents.
- `src/jingyantai/agents/roles.py`
  Concrete role classes that use the task-level tool layer and can later be swapped to deepagents-backed implementations.
- `src/jingyantai/runtime/compactor.py`
  Context compaction logic for hot/warm carry-forward context.
- `src/jingyantai/runtime/judges.py`
  Evidence, coverage, challenger, and stop judge implementations.
- `src/jingyantai/runtime/reporting.py`
  Draft synthesis and citation attachment.
- `src/jingyantai/runtime/controller.py`
  Harness controller, phase transitions, gap routing, budgets, and circuit breakers.
- `tests/conftest.py`
  Shared pytest fixtures and temporary run directory fixture.
- `tests/fakes.py`
  Fake agents and fake toolset for deterministic controller tests.
- `tests/test_fakes_contracts.py`
  Fake agent contract tests.
- `tests/test_bootstrap.py`
  Package bootstrap tests.
- `tests/test_domain_models.py`
  Model and state machine tests.
- `tests/test_run_store.py`
  Persistence and checkpoint tests.
- `tests/test_research_tools.py`
  Task-level tool behavior tests.
- `tests/test_judges.py`
  Judge and stop gate tests.
- `tests/test_controller.py`
  Harness loop tests.
- `tests/test_reporting.py`
  Synthesis and citation tests.
- `tests/test_deepagents_adapter.py`
  Adapter mapping tests with a fake runner.
- `tests/test_cli.py`
  CLI run command tests.

### Task 1: Bootstrap The Project Skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `README.md`
- Create: `src/jingyantai/__init__.py`
- Create: `src/jingyantai/cli.py`
- Create: `tests/test_bootstrap.py`

- [ ] **Step 1: Write the failing bootstrap test**

```python
# tests/test_bootstrap.py
from jingyantai import __version__
from jingyantai.cli import app


def test_package_exposes_version_and_cli_name():
    assert __version__ == "0.1.0"
    assert app.info.name == "jingyantai"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bootstrap.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jingyantai'`

- [ ] **Step 3: Write the minimal bootstrap implementation**

```toml
# pyproject.toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "jingyantai"
version = "0.1.0"
description = "Long-running competitive research harness for small teams."
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
  "beautifulsoup4>=4.12",
  "httpx>=0.27",
  "pydantic>=2.7",
  "pydantic-settings>=2.2",
  "rich>=13.7",
  "typer>=0.12",
]

[project.optional-dependencies]
deepagents = [
  "deepagents @ git+https://github.com/langchain-ai/deepagents.git",
]
dev = [
  "pytest>=8.2",
  "pytest-cov>=5.0",
]

[project.scripts]
jingyantai = "jingyantai.cli:app"

[tool.pytest.ini_options]
pythonpath = ["src"]
```

```gitignore
# .gitignore
.env
.venv
__pycache__
.pytest_cache
*.pyc
runs
dist
build
```

```env
# .env.example
MODEL_PROVIDER=anthropic
MODEL_NAME=claude-3-7-sonnet-latest
TAVILY_API_KEY=
GITHUB_TOKEN=
RUNS_DIR=./runs
```

```markdown
# README.md

# 竞研台

面向小团队的长程竞品研究 Harness。

## Current Scope

- `Claude Code` 竞品研究 MVP
- 长程运行直到 `Stop Judge` 放行
- 生成侧与评估侧严格分离

## Planned Commands

```bash
pip install -e .[dev]
jingyantai --help
```
```

```python
# src/jingyantai/__init__.py
__version__ = "0.1.0"
```

```python
# src/jingyantai/cli.py
import typer

app = typer.Typer(name="jingyantai", no_args_is_help=True)


@app.callback()
def main() -> None:
    """竞研台 CLI."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_bootstrap.py -v`
Expected: PASS with `1 passed`

- [ ] **Step 5: Initialize git and commit the scaffold**

```bash
git init
git add pyproject.toml .gitignore .env.example README.md src/jingyantai/__init__.py src/jingyantai/cli.py tests/test_bootstrap.py
git commit -m "chore: bootstrap jingyantai package"
```

### Task 2: Define Runtime Enums, Data Models, And Candidate State Machine

**Files:**
- Create: `src/jingyantai/domain/phases.py`
- Create: `src/jingyantai/domain/models.py`
- Create: `tests/test_domain_models.py`

- [ ] **Step 1: Write the failing model tests**

```python
# tests/test_domain_models.py
import pytest

from jingyantai.domain.models import BudgetPolicy, Candidate, RunState
from jingyantai.domain.phases import CandidateStatus, Phase


def test_candidate_rejects_invalid_status_jump():
    candidate = Candidate(
        candidate_id="c1",
        name="OpenAI Codex CLI",
        canonical_url="https://openai.com",
        status=CandidateStatus.DISCOVERED,
        relevance_score=0.5,
        why_candidate="Terminal coding agent",
    )

    with pytest.raises(ValueError):
        candidate.transition_to(CandidateStatus.PRIORITIZED)


def test_run_state_returns_top_candidates_in_priority_order():
    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.CONVERGE,
        budget=BudgetPolicy(max_rounds=4, max_active_candidates=8, max_deepen_targets=3, max_external_fetches=30, max_run_duration_minutes=20),
    )
    state.candidates.extend(
        [
            Candidate(candidate_id="a", name="A", canonical_url="https://a.dev", status=CandidateStatus.PRIORITIZED, relevance_score=0.6, why_candidate="A"),
            Candidate(candidate_id="b", name="B", canonical_url="https://b.dev", status=CandidateStatus.PRIORITIZED, relevance_score=0.9, why_candidate="B"),
            Candidate(candidate_id="c", name="C", canonical_url="https://c.dev", status=CandidateStatus.REJECTED, relevance_score=0.99, why_candidate="C"),
        ]
    )

    assert [candidate.name for candidate in state.top_candidates(limit=2)] == ["B", "A"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_domain_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jingyantai.domain'`

- [ ] **Step 3: Write the domain models and state machine**

```python
# src/jingyantai/domain/phases.py
from enum import StrEnum


class Phase(StrEnum):
    INITIALIZE = "initialize"
    EXPAND = "expand"
    CONVERGE = "converge"
    DEEPEN = "deepen"
    CHALLENGE = "challenge"
    DECIDE = "decide"
    STOP = "stop"


class CandidateStatus(StrEnum):
    DISCOVERED = "discovered"
    NORMALIZED = "normalized"
    PLAUSIBLE = "plausible"
    PRIORITIZED = "prioritized"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class HypothesisStatus(StrEnum):
    UNTESTED = "untested"
    SUPPORTED = "supported"
    WEAKENED = "weakened"
    REJECTED = "rejected"


class ReviewVerdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


class StopVerdict(StrEnum):
    STOP = "stop"
    CONTINUE = "continue"


class GapPriority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
```

```python
# src/jingyantai/domain/models.py
from __future__ import annotations

from pydantic import BaseModel, Field

from jingyantai.domain.phases import CandidateStatus, GapPriority, HypothesisStatus, Phase, ReviewVerdict, StopVerdict


class BudgetPolicy(BaseModel):
    max_rounds: int
    max_active_candidates: int
    max_deepen_targets: int
    max_external_fetches: int
    max_run_duration_minutes: int


class ResearchBrief(BaseModel):
    target: str
    product_type: str
    competitor_definition: str
    required_dimensions: list[str]
    budget: BudgetPolicy
    stop_policy: str


class RunCharter(BaseModel):
    mission: str
    scope: list[str]
    non_goals: list[str]
    success_criteria: list[str]
    research_agenda: list[str]


class Hypothesis(BaseModel):
    statement: str
    status: HypothesisStatus = HypothesisStatus.UNTESTED
    related_candidates: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    conflicting_evidence_ids: list[str] = Field(default_factory=list)


class Candidate(BaseModel):
    candidate_id: str
    name: str
    canonical_url: str
    status: CandidateStatus
    relevance_score: float
    why_candidate: str
    aliases: list[str] = Field(default_factory=list)
    company: str | None = None
    why_not_candidate: str | None = None

    def transition_to(self, new_status: CandidateStatus) -> None:
        valid_transitions = {
            CandidateStatus.DISCOVERED: {CandidateStatus.NORMALIZED, CandidateStatus.REJECTED},
            CandidateStatus.NORMALIZED: {CandidateStatus.PLAUSIBLE, CandidateStatus.REJECTED},
            CandidateStatus.PLAUSIBLE: {CandidateStatus.PRIORITIZED, CandidateStatus.REJECTED},
            CandidateStatus.PRIORITIZED: {CandidateStatus.CONFIRMED, CandidateStatus.REJECTED},
            CandidateStatus.CONFIRMED: set(),
            CandidateStatus.REJECTED: set(),
        }
        if new_status not in valid_transitions[self.status]:
            raise ValueError(f"Invalid status transition: {self.status} -> {new_status}")
        self.status = new_status


class Evidence(BaseModel):
    evidence_id: str
    subject_id: str
    claim: str
    source_url: str
    source_type: str
    snippet: str
    captured_at: str
    freshness_score: float
    confidence: float
    supports_or_conflicts: str = "supports"


class Finding(BaseModel):
    finding_id: str
    subject_id: str
    dimension: str
    summary: str
    evidence_ids: list[str]
    confidence: float
    conflict_flags: list[str] = Field(default_factory=list)


class OpenQuestion(BaseModel):
    question: str
    target_subject: str
    priority: GapPriority
    owner_role: str
    created_by: str


class UncertaintyItem(BaseModel):
    statement: str
    impact: str
    resolvability: str
    required_evidence: str
    owner_role: str


class GapTicket(BaseModel):
    gap_type: str
    target_scope: str
    blocking_reason: str
    owner_role: str
    acceptance_rule: str
    deadline_round: int
    priority: GapPriority
    retry_count: int = 0


class ReviewDecision(BaseModel):
    judge_type: str
    target_scope: str
    verdict: ReviewVerdict
    reasons: list[str]
    required_actions: list[str] = Field(default_factory=list)


class StopDecision(BaseModel):
    verdict: StopVerdict
    reasons: list[str]
    gap_tickets: list[GapTicket] = Field(default_factory=list)


class RunTrace(BaseModel):
    round_index: int
    phase: Phase
    planner_output: str
    dispatched_tasks: list[str]
    new_candidates: list[str]
    new_findings: list[str]
    review_decisions: list[str]
    stop_or_continue: str


class FinalReport(BaseModel):
    target_summary: str
    confirmed_competitors: list[str]
    rejected_candidates: list[str]
    comparison_matrix: list[dict[str, str]]
    key_uncertainties: list[str]
    citations: dict[str, list[str]]


class RunState(BaseModel):
    run_id: str
    target: str
    current_phase: Phase
    budget: BudgetPolicy
    brief: ResearchBrief | None = None
    charter: RunCharter | None = None
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    candidates: list[Candidate] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    uncertainties: list[UncertaintyItem] = Field(default_factory=list)
    gap_tickets: list[GapTicket] = Field(default_factory=list)
    review_decisions: list[ReviewDecision] = Field(default_factory=list)
    traces: list[RunTrace] = Field(default_factory=list)
    final_report: FinalReport | None = None
    round_index: int = 0
    external_fetch_count: int = 0
    carry_forward_context: str = ""

    def top_candidates(self, limit: int) -> list[Candidate]:
        prioritized = [
            candidate
            for candidate in self.candidates
            if candidate.status in {CandidateStatus.PRIORITIZED, CandidateStatus.CONFIRMED}
        ]
        return sorted(prioritized, key=lambda candidate: candidate.relevance_score, reverse=True)[:limit]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_domain_models.py -v`
Expected: PASS with `2 passed`

- [ ] **Step 5: Commit the domain model layer**

```bash
git add src/jingyantai/domain/phases.py src/jingyantai/domain/models.py tests/test_domain_models.py
git commit -m "feat: add runtime domain models and candidate state machine"
```

### Task 3: Add A File-Backed Run Store For State, Traces, And Artifacts

**Files:**
- Create: `src/jingyantai/storage/run_store.py`
- Create: `tests/test_run_store.py`

- [ ] **Step 1: Write the failing run store tests**

```python
# tests/test_run_store.py
from pathlib import Path

from jingyantai.domain.models import BudgetPolicy, RunState, RunTrace
from jingyantai.domain.phases import Phase
from jingyantai.storage.run_store import FileRunStore


def test_run_store_persists_and_loads_state(tmp_path: Path):
    store = FileRunStore(tmp_path)
    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.INITIALIZE,
        budget=BudgetPolicy(max_rounds=4, max_active_candidates=8, max_deepen_targets=3, max_external_fetches=30, max_run_duration_minutes=20),
    )

    store.save_state(state)
    loaded = store.load_state("run-1")

    assert loaded.run_id == "run-1"
    assert loaded.target == "Claude Code"


def test_run_store_appends_trace_files(tmp_path: Path):
    store = FileRunStore(tmp_path)
    trace = RunTrace(
        round_index=0,
        phase=Phase.INITIALIZE,
        planner_output="Create charter",
        dispatched_tasks=[],
        new_candidates=[],
        new_findings=[],
        review_decisions=[],
        stop_or_continue="continue",
    )

    store.append_trace("run-1", trace)

    assert (tmp_path / "run-1" / "traces" / "000-initialize.json").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_run_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jingyantai.storage'`

- [ ] **Step 3: Write the file-backed run store**

```python
# src/jingyantai/storage/run_store.py
from __future__ import annotations

import json
from pathlib import Path

from jingyantai.domain.models import FinalReport, RunState, RunTrace


class FileRunStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _run_dir(self, run_id: str) -> Path:
        return self.root / run_id

    def save_state(self, state: RunState) -> None:
        run_dir = self._run_dir(state.run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "artifacts").mkdir(exist_ok=True)
        (run_dir / "traces").mkdir(exist_ok=True)
        (run_dir / "state.json").write_text(state.model_dump_json(indent=2), encoding="utf-8")

    def load_state(self, run_id: str) -> RunState:
        payload = json.loads((self._run_dir(run_id) / "state.json").read_text(encoding="utf-8"))
        return RunState.model_validate(payload)

    def append_trace(self, run_id: str, trace: RunTrace) -> None:
        trace_dir = self._run_dir(run_id) / "traces"
        trace_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{trace.round_index:03d}-{trace.phase.value}.json"
        (trace_dir / filename).write_text(trace.model_dump_json(indent=2), encoding="utf-8")

    def save_report(self, run_id: str, report: FinalReport) -> Path:
        artifacts_dir = self._run_dir(run_id) / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        report_path = artifacts_dir / "final-report.json"
        report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return report_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_run_store.py -v`
Expected: PASS with `2 passed`

- [ ] **Step 5: Commit the persistence layer**

```bash
git add src/jingyantai/storage/run_store.py tests/test_run_store.py
git commit -m "feat: add file-backed run store"
```

### Task 4: Implement Research Tool Contracts And Real Web/GitHub Signal Adapters

**Files:**
- Create: `src/jingyantai/tools/contracts.py`
- Create: `src/jingyantai/tools/web_search.py`
- Create: `src/jingyantai/tools/page_extract.py`
- Create: `src/jingyantai/tools/github_signals.py`
- Create: `src/jingyantai/tools/research_tools.py`
- Create: `tests/test_research_tools.py`

- [ ] **Step 1: Write the failing research tool tests**

```python
# tests/test_research_tools.py
from jingyantai.tools.research_tools import ResearchTools


class FakeSearchClient:
    def search(self, query: str, max_results: int = 5) -> list[dict[str, str]]:
        return [
            {"title": "OpenAI Codex CLI", "url": "https://openai.com/index/introducing-codex/", "snippet": "CLI coding agent"},
            {"title": "Aider", "url": "https://aider.chat/", "snippet": "AI pair programming in the terminal"},
        ]


class FakePageExtractor:
    def extract(self, url: str) -> dict[str, str]:
        return {"url": url, "title": "Aider", "text": "Aider is an AI pair programmer in your terminal."}


class FakeGitHubSignals:
    def lookup(self, query: str) -> list[dict[str, str | int]]:
        return [{"repo": "Aider-AI/aider", "stars": 24000, "releases": 100}]


def test_search_competitor_candidates_returns_structured_candidates():
    tools = ResearchTools(
        search_client=FakeSearchClient(),
        page_extractor=FakePageExtractor(),
        github_signals=FakeGitHubSignals(),
    )

    results = tools.search_competitor_candidates("Claude Code", "terminal coding agents", ["web", "github"])

    assert results[0]["name"] == "OpenAI Codex CLI"
    assert results[1]["canonical_url"] == "https://aider.chat/"


def test_collect_market_heat_signals_merges_page_and_github_data():
    tools = ResearchTools(
        search_client=FakeSearchClient(),
        page_extractor=FakePageExtractor(),
        github_signals=FakeGitHubSignals(),
    )

    signals = tools.collect_market_heat_signals("Aider")

    assert signals["summary"].startswith("Aider")
    assert signals["github"][0]["repo"] == "Aider-AI/aider"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_research_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jingyantai.tools'`

- [ ] **Step 3: Write task-level research tools and provider adapters**

```python
# src/jingyantai/tools/contracts.py
from __future__ import annotations

from typing import Protocol


class SearchClient(Protocol):
    def search(self, query: str, max_results: int = 5) -> list[dict[str, str]]: ...


class PageExtractor(Protocol):
    def extract(self, url: str) -> dict[str, str]: ...


class GitHubSignalsClient(Protocol):
    def lookup(self, query: str) -> list[dict[str, str | int]]: ...
```

```python
# src/jingyantai/tools/web_search.py
from __future__ import annotations

import httpx


class TavilySearchClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def search(self, query: str, max_results: int = 5) -> list[dict[str, str]]:
        response = httpx.post(
            "https://api.tavily.com/search",
            json={"api_key": self.api_key, "query": query, "max_results": max_results},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        return [
            {
                "title": item["title"],
                "url": item["url"],
                "snippet": item["content"],
            }
            for item in payload.get("results", [])
        ]
```

```python
# src/jingyantai/tools/page_extract.py
from __future__ import annotations

from bs4 import BeautifulSoup
import httpx


class HttpPageExtractor:
    def __init__(self, timeout_seconds: int = 10) -> None:
        self.timeout_seconds = timeout_seconds

    def extract(self, url: str) -> dict[str, str]:
        response = httpx.get(url, timeout=self.timeout_seconds)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else url
        text = " ".join(soup.stripped_strings)
        return {"url": url, "title": title, "text": text[:4000]}
```

```python
# src/jingyantai/tools/github_signals.py
from __future__ import annotations

import httpx


class GitHubSignals:
    def __init__(self, token: str | None = None) -> None:
        self.token = token

    def lookup(self, query: str) -> list[dict[str, str | int]]:
        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        response = httpx.get(
            "https://api.github.com/search/repositories",
            params={"q": query, "per_page": 3},
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        return [
            {
                "repo": item["full_name"],
                "stars": item["stargazers_count"],
                "releases": item.get("open_issues_count", 0),
            }
            for item in payload.get("items", [])
        ]
```

```python
# src/jingyantai/tools/research_tools.py
from __future__ import annotations

from jingyantai.tools.contracts import GitHubSignalsClient, PageExtractor, SearchClient


class ResearchTools:
    def __init__(self, search_client: SearchClient, page_extractor: PageExtractor, github_signals: GitHubSignalsClient) -> None:
        self.search_client = search_client
        self.page_extractor = page_extractor
        self.github_signals = github_signals

    def search_competitor_candidates(self, target: str, hypothesis: str, source_mix: list[str]) -> list[dict[str, str]]:
        query = f"{target} competitor {hypothesis}"
        results = self.search_client.search(query, max_results=5)
        candidates: list[dict[str, str]] = []
        for item in results:
            candidates.append(
                {
                    "name": item["title"],
                    "canonical_url": item["url"],
                    "why_candidate": item["snippet"],
                }
            )
        return candidates

    def collect_positioning_evidence(self, subject: str, url: str) -> dict[str, str]:
        page = self.page_extractor.extract(url)
        return {"subject": subject, "dimension": "positioning", "summary": page["text"][:600], "source_url": url}

    def collect_workflow_evidence(self, subject: str, url: str) -> dict[str, str]:
        page = self.page_extractor.extract(url)
        return {"subject": subject, "dimension": "workflow", "summary": page["text"][:600], "source_url": url}

    def collect_pricing_access_evidence(self, subject: str, url: str) -> dict[str, str]:
        page = self.page_extractor.extract(url)
        return {"subject": subject, "dimension": "pricing or access", "summary": page["text"][:600], "source_url": url}

    def collect_github_ecosystem_signals(self, subject: str) -> list[dict[str, str | int]]:
        return self.github_signals.lookup(subject)

    def collect_market_heat_signals(self, subject: str) -> dict[str, object]:
        search_hits = self.search_client.search(subject, max_results=3)
        github_hits = self.github_signals.lookup(subject)
        summary = search_hits[0]["snippet"] if search_hits else f"{subject} has no search summary."
        return {"summary": summary, "search": search_hits, "github": github_hits}

    def build_evidence_bundle(self, subject: str, url: str) -> dict[str, object]:
        return {
            "positioning": self.collect_positioning_evidence(subject, url),
            "workflow": self.collect_workflow_evidence(subject, url),
            "pricing_or_access": self.collect_pricing_access_evidence(subject, url),
            "github": self.collect_github_ecosystem_signals(subject),
            "heat": self.collect_market_heat_signals(subject),
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_research_tools.py -v`
Expected: PASS with `2 passed`

- [ ] **Step 5: Commit the real research tool layer**

```bash
git add src/jingyantai/tools/contracts.py src/jingyantai/tools/web_search.py src/jingyantai/tools/page_extract.py src/jingyantai/tools/github_signals.py src/jingyantai/tools/research_tools.py tests/test_research_tools.py
git commit -m "feat: add research tool contracts and web/github signal adapters"
```

### Task 5: Add Agent Contracts, Role Prompts, And Deterministic Test Doubles

**Files:**
- Create: `src/jingyantai/agents/contracts.py`
- Create: `src/jingyantai/agents/prompts.py`
- Create: `tests/conftest.py`
- Create: `tests/fakes.py`
- Create: `tests/test_fakes_contracts.py`

- [ ] **Step 1: Write the failing contract and fake-agent tests**

```python
# tests/conftest.py
from pathlib import Path

import pytest


@pytest.fixture
def runs_dir(tmp_path: Path) -> Path:
    return tmp_path / "runs"
```

```python
# tests/fakes.py
from jingyantai.domain.models import BudgetPolicy, Candidate, ResearchBrief, RunCharter, StopDecision
from jingyantai.domain.phases import CandidateStatus, Phase, StopVerdict


class FakeInitializer:
    def run(self, target: str) -> tuple[ResearchBrief, RunCharter]:
        return (
            ResearchBrief(
                target=target,
                product_type="coding-agent",
                competitor_definition="Direct competitors are terminal-native coding agents for software engineers.",
                required_dimensions=["positioning", "workflow", "core capabilities", "pricing or access", "community / ecosystem signal"],
                stop_policy="Stop after enough confirmed competitors with coverage.",
            ),
            RunCharter(
                mission=f"Research competitors for {target}",
                scope=["direct competitors", "terminal coding agents"],
                non_goals=["broad LLM platform analysis"],
                success_criteria=["3 confirmed competitors", "all required dimensions covered"],
                research_agenda=["expand", "deepen", "challenge"],
            ),
        )


class FakeStopJudge:
    def __init__(self, verdict: StopVerdict) -> None:
        self.verdict = verdict

    def run(self, _state):
        return StopDecision(verdict=self.verdict, reasons=["test verdict"])
```

```python
# tests/test_fakes_contracts.py
from tests.fakes import FakeInitializer, FakeStopJudge
from jingyantai.domain.phases import StopVerdict


def test_fake_initializer_returns_brief_and_charter():
    brief, charter = FakeInitializer().run("Claude Code")
    assert brief.target == "Claude Code"
    assert charter.scope == ["direct competitors", "terminal coding agents"]


def test_fake_stop_judge_returns_structured_stop_decision():
    decision = FakeStopJudge(StopVerdict.CONTINUE).run(None)
    assert decision.verdict == StopVerdict.CONTINUE
    assert decision.reasons == ["test verdict"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fakes_contracts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tests.fakes'` or `No module named 'jingyantai.agents'`

- [ ] **Step 3: Write agent contracts and role prompts**

```python
# src/jingyantai/agents/contracts.py
from __future__ import annotations

from typing import Protocol

from jingyantai.domain.models import Candidate, Evidence, Finding, GapTicket, ResearchBrief, RunCharter, RunState, StopDecision, UncertaintyItem


class InitializerAgent(Protocol):
    def run(self, target: str) -> tuple[ResearchBrief, RunCharter]: ...


class LeadResearcherAgent(Protocol):
    def run(self, state: RunState) -> str: ...


class ScoutAgent(Protocol):
    def run(self, state: RunState) -> list[Candidate]: ...


class AnalystAgent(Protocol):
    def run(self, state: RunState, candidate: Candidate) -> tuple[list[Evidence], list[Finding], list[UncertaintyItem]]: ...


class JudgeAgent(Protocol):
    def run(self, state: RunState): ...


class StopJudgeAgent(Protocol):
    def run(self, state: RunState) -> StopDecision: ...


class SynthesizerAgent(Protocol):
    def run(self, state: RunState): ...


class CitationAgent(Protocol):
    def run(self, state: RunState): ...
```

```python
# src/jingyantai/agents/prompts.py
ROLE_PROMPTS = {
    "initializer": "You are the Initializer. Produce a tight research brief, charter, and direct competitor definition.",
    "lead_researcher": "You are the Lead Researcher. Plan the next round only from the current run state and gap tickets.",
    "scout_positioning": "You are a Scout Agent. Expand the candidate pool for terminal-native coding agents.",
    "scout_github": "You are a Scout Agent. Use GitHub and ecosystem signals to surface relevant competitors.",
    "scout_heat": "You are a Scout Agent. Look for current community heat around developer agent products.",
    "analyst_workflow": "You are an Analyst Agent. Deepen workflow and capability evidence for a prioritized candidate.",
    "analyst_pricing": "You are an Analyst Agent. Deepen pricing and access evidence for a prioritized candidate.",
    "analyst_positioning": "You are an Analyst Agent. Deepen positioning and user-segment evidence for a prioritized candidate.",
    "evidence_judge": "You are the Evidence Judge. Reject weak, old, or indirect evidence.",
    "coverage_judge": "You are the Coverage Judge. Find uncovered required dimensions.",
    "challenger": "You are the Challenger. Try to prove a candidate is not a direct competitor.",
    "stop_judge": "You are the Stop Judge. Return STOP only when the quality bar is met.",
    "synthesizer": "You are the Synthesizer. Draft a report from confirmed findings only.",
    "citation_agent": "You are the Citation Agent. Attach source URLs to every factual claim.",
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_fakes_contracts.py -v`
Expected: PASS with `2 passed`

- [ ] **Step 5: Commit contracts and prompts**

```bash
git add src/jingyantai/agents/contracts.py src/jingyantai/agents/prompts.py tests/conftest.py tests/fakes.py tests/test_fakes_contracts.py
git commit -m "feat: add agent role contracts and prompt registry"
```

### Task 6: Implement Context Compaction And The Evaluation Layer

**Files:**
- Create: `src/jingyantai/runtime/compactor.py`
- Create: `src/jingyantai/runtime/judges.py`
- Create: `tests/test_judges.py`

- [ ] **Step 1: Write the failing judge tests**

```python
# tests/test_judges.py
from jingyantai.domain.models import BudgetPolicy, Candidate, Evidence, Finding, RunState
from jingyantai.domain.phases import CandidateStatus, Phase, StopVerdict
from jingyantai.runtime.compactor import ContextCompactor
from jingyantai.runtime.judges import CoverageJudge, EvidenceJudge, StopJudge


def test_stop_judge_returns_continue_when_confirmed_candidates_lack_coverage():
    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.DECIDE,
        budget=BudgetPolicy(max_rounds=4, max_active_candidates=8, max_deepen_targets=3, max_external_fetches=30, max_run_duration_minutes=20),
    )
    state.candidates.append(
        Candidate(candidate_id="a", name="Aider", canonical_url="https://aider.chat", status=CandidateStatus.CONFIRMED, relevance_score=0.92, why_candidate="terminal coding agent")
    )
    state.findings.append(
        Finding(finding_id="f1", subject_id="a", dimension="positioning", summary="Terminal coding agent", evidence_ids=["e1"], confidence=0.9)
    )
    state.evidence.append(
        Evidence(evidence_id="e1", subject_id="a", claim="Aider is terminal-based", source_url="https://aider.chat", source_type="official", snippet="AI pair programmer in your terminal", captured_at="2026-04-01", freshness_score=0.9, confidence=0.9)
    )

    decision = StopJudge(required_dimensions=["positioning", "workflow", "pricing or access"]).run(state)

    assert decision.verdict == StopVerdict.CONTINUE
    assert decision.gap_tickets[0].owner_role == "analyst"


def test_context_compactor_produces_carry_forward_snapshot():
    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.CHALLENGE,
        budget=BudgetPolicy(max_rounds=4, max_active_candidates=8, max_deepen_targets=3, max_external_fetches=30, max_run_duration_minutes=20),
    )
    state.candidates.append(
        Candidate(candidate_id="a", name="Aider", canonical_url="https://aider.chat", status=CandidateStatus.PRIORITIZED, relevance_score=0.92, why_candidate="terminal coding agent")
    )

    carry = ContextCompactor().compact(state)

    assert "Aider" in carry
    assert "Claude Code" in carry
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_judges.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jingyantai.runtime'`

- [ ] **Step 3: Write the compactor and judge implementations**

```python
# src/jingyantai/runtime/compactor.py
from __future__ import annotations

from jingyantai.domain.models import RunState


class ContextCompactor:
    def compact(self, state: RunState) -> str:
        top_candidates = ", ".join(candidate.name for candidate in state.top_candidates(limit=3)) or "none"
        open_questions = ", ".join(question.question for question in state.open_questions[:3]) or "none"
        return (
            f"target={state.target}; "
            f"phase={state.current_phase.value}; "
            f"top_candidates={top_candidates}; "
            f"open_questions={open_questions}"
        )
```

```python
# src/jingyantai/runtime/judges.py
from __future__ import annotations

from collections import defaultdict

from jingyantai.domain.models import GapTicket, ReviewDecision, RunState, StopDecision
from jingyantai.domain.phases import CandidateStatus, GapPriority, ReviewVerdict, StopVerdict


class EvidenceJudge:
    def run(self, state: RunState) -> ReviewDecision:
        weak_evidence = [evidence.evidence_id for evidence in state.evidence if evidence.confidence < 0.6]
        verdict = ReviewVerdict.FAIL if weak_evidence else ReviewVerdict.PASS
        return ReviewDecision(
            judge_type="evidence",
            target_scope="run",
            verdict=verdict,
            reasons=["weak evidence found"] if weak_evidence else ["evidence quality is acceptable"],
            required_actions=weak_evidence,
        )


class CoverageJudge:
    def __init__(self, required_dimensions: list[str]) -> None:
        self.required_dimensions = required_dimensions

    def run(self, state: RunState) -> ReviewDecision:
        dimensions_by_subject: dict[str, set[str]] = defaultdict(set)
        for finding in state.findings:
            dimensions_by_subject[finding.subject_id].add(finding.dimension)
        missing = []
        for candidate in state.candidates:
            if candidate.status != CandidateStatus.CONFIRMED:
                continue
            missing_dimensions = sorted(set(self.required_dimensions) - dimensions_by_subject[candidate.candidate_id])
            if missing_dimensions:
                missing.append(f"{candidate.name}:{','.join(missing_dimensions)}")
        verdict = ReviewVerdict.FAIL if missing else ReviewVerdict.PASS
        return ReviewDecision(
            judge_type="coverage",
            target_scope="confirmed_candidates",
            verdict=verdict,
            reasons=missing or ["coverage requirements satisfied"],
            required_actions=missing,
        )


class Challenger:
    def run(self, state: RunState) -> ReviewDecision:
        suspicious = [candidate.name for candidate in state.candidates if "platform" in candidate.why_candidate.lower()]
        verdict = ReviewVerdict.WARN if suspicious else ReviewVerdict.PASS
        return ReviewDecision(
            judge_type="challenger",
            target_scope="candidate_fit",
            verdict=verdict,
            reasons=suspicious or ["no direct-competitor objections"],
        )


class StopJudge:
    def __init__(self, required_dimensions: list[str]) -> None:
        self.required_dimensions = required_dimensions

    def run(self, state: RunState) -> StopDecision:
        confirmed = [candidate for candidate in state.candidates if candidate.status == CandidateStatus.CONFIRMED]
        dimensions_by_subject: dict[str, set[str]] = defaultdict(set)
        for finding in state.findings:
            dimensions_by_subject[finding.subject_id].add(finding.dimension)
        gap_tickets = []
        for candidate in confirmed:
            missing = sorted(set(self.required_dimensions) - dimensions_by_subject[candidate.candidate_id])
            if missing:
                gap_tickets.append(
                    GapTicket(
                        gap_type="coverage",
                        target_scope=candidate.name,
                        blocking_reason=f"Missing dimensions: {', '.join(missing)}",
                        owner_role="analyst",
                        acceptance_rule="Cover all required dimensions with direct evidence.",
                        deadline_round=state.round_index + 1,
                        priority=GapPriority.HIGH,
                    )
                )
        if len(confirmed) < 3:
            gap_tickets.append(
                GapTicket(
                    gap_type="candidate_count",
                    target_scope="run",
                    blocking_reason="Need at least 3 confirmed competitors.",
                    owner_role="scout",
                    acceptance_rule="Confirm at least 3 direct competitors.",
                    deadline_round=state.round_index + 1,
                    priority=GapPriority.HIGH,
                )
            )
        verdict = StopVerdict.CONTINUE if gap_tickets else StopVerdict.STOP
        reasons = ["Quality bar not met"] if gap_tickets else ["Quality bar met"]
        return StopDecision(verdict=verdict, reasons=reasons, gap_tickets=gap_tickets)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_judges.py -v`
Expected: PASS with `2 passed`

- [ ] **Step 5: Commit the evaluation layer**

```bash
git add src/jingyantai/runtime/compactor.py src/jingyantai/runtime/judges.py tests/test_judges.py
git commit -m "feat: add compactor and evaluation judges"
```

### Task 7: Build The Harness Controller And Phase Loop

**Files:**
- Create: `src/jingyantai/runtime/controller.py`
- Create: `tests/test_controller.py`

- [ ] **Step 1: Write the failing controller loop test**

```python
# tests/test_controller.py
from pathlib import Path

from jingyantai.domain.models import BudgetPolicy
from jingyantai.domain.phases import StopVerdict
from jingyantai.runtime.compactor import ContextCompactor
from jingyantai.runtime.controller import HarnessController
from jingyantai.storage.run_store import FileRunStore
from tests.fakes import FakeInitializer


class FakeLeadResearcher:
    def run(self, state):
        return "Investigate terminal-native coding agents and deepen top candidates."


class FakeScout:
    def __init__(self, suffix: str):
        self.suffix = suffix

    def run(self, state):
        from jingyantai.domain.models import Candidate
        from jingyantai.domain.phases import CandidateStatus

        return [
            Candidate(
                candidate_id=f"{self.suffix}-1",
                name=f"{self.suffix} Candidate",
                canonical_url=f"https://{self.suffix}.dev",
                status=CandidateStatus.DISCOVERED,
                relevance_score=0.8,
                why_candidate="terminal coding agent",
            )
        ]


class FakeAnalyst:
    def run(self, state, candidate):
        from jingyantai.domain.models import Evidence, Finding

        evidence = Evidence(
            evidence_id=f"e-{candidate.candidate_id}",
            subject_id=candidate.candidate_id,
            claim=f"{candidate.name} is a direct competitor",
            source_url=candidate.canonical_url,
            source_type="official",
            snippet="Direct evidence",
            captured_at="2026-04-01",
            freshness_score=0.95,
            confidence=0.95,
        )
        finding = Finding(
            finding_id=f"f-{candidate.candidate_id}",
            subject_id=candidate.candidate_id,
            dimension="positioning",
            summary=f"{candidate.name} overlaps with Claude Code",
            evidence_ids=[evidence.evidence_id],
            confidence=0.95,
        )
        return [evidence], [finding], []


class SequentialStopJudge:
    def __init__(self, verdicts):
        self.verdicts = verdicts
        self.index = 0

    def run(self, state):
        from jingyantai.domain.models import GapTicket, StopDecision
        from jingyantai.domain.phases import GapPriority

        verdict = self.verdicts[min(self.index, len(self.verdicts) - 1)]
        self.index += 1
        if verdict == StopVerdict.CONTINUE:
            return StopDecision(
                verdict=verdict,
                reasons=["Need one more deepen pass"],
                gap_tickets=[
                    GapTicket(
                        gap_type="coverage",
                        target_scope="confirmed_candidates",
                        blocking_reason="Need another workflow pass",
                        owner_role="analyst",
                        acceptance_rule="Add one more workflow finding",
                        deadline_round=state.round_index + 1,
                        priority=GapPriority.HIGH,
                    )
                ],
            )
        return StopDecision(verdict=verdict, reasons=["Enough coverage"])


def test_controller_loops_until_stop_and_persists_state(tmp_path: Path):
    store = FileRunStore(tmp_path / "runs")
    controller = HarnessController(
        store=store,
        initializer=FakeInitializer(),
        lead_researcher=FakeLeadResearcher(),
        scouts=[FakeScout("aider"), FakeScout("codex"), FakeScout("opencode")],
        analysts=[FakeAnalyst()],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=lambda state: None,
        challenger=lambda state: None,
        stop_judge=SequentialStopJudge([StopVerdict.CONTINUE, StopVerdict.STOP]),
    )

    final_state = controller.run(
        target="Claude Code",
        budget=BudgetPolicy(max_rounds=4, max_active_candidates=8, max_deepen_targets=3, max_external_fetches=30, max_run_duration_minutes=20),
    )

    assert final_state.current_phase.value == "stop"
    assert store.load_state(final_state.run_id).target == "Claude Code"
    assert final_state.round_index == 1
    assert "Claude Code" in final_state.carry_forward_context
    assert len(final_state.traces) >= 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_controller.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jingyantai.runtime.controller'`

- [ ] **Step 3: Implement the phase-driven harness controller**

```python
# src/jingyantai/runtime/controller.py
from __future__ import annotations

from datetime import datetime

from jingyantai.domain.models import BudgetPolicy, RunState, RunTrace
from jingyantai.domain.phases import CandidateStatus, Phase, StopVerdict


class HarnessController:
    def __init__(
        self,
        store,
        initializer,
        lead_researcher,
        scouts,
        analysts,
        compactor,
        evidence_judge,
        coverage_judge,
        challenger,
        stop_judge,
    ) -> None:
        self.store = store
        self.initializer = initializer
        self.lead_researcher = lead_researcher
        self.scouts = scouts
        self.analysts = analysts
        self.compactor = compactor
        self.evidence_judge = evidence_judge
        self.coverage_judge = coverage_judge
        self.challenger = challenger
        self.stop_judge = stop_judge

    def run(self, target: str, budget: BudgetPolicy) -> RunState:
        run_id = datetime.utcnow().strftime("run-%Y%m%d%H%M%S")
        state = RunState(run_id=run_id, target=target, current_phase=Phase.INITIALIZE, budget=budget)

        brief, charter = self.initializer.run(target)
        state.brief = brief
        state.charter = charter
        self._trace(state, "created brief and charter")

        while state.round_index <= state.budget.max_rounds:
            if state.round_index == 0 or any(ticket.owner_role == "scout" for ticket in state.gap_tickets):
                state.current_phase = Phase.EXPAND
                round_plan = self.lead_researcher.run(state)
                for scout in self.scouts:
                    for candidate in scout.run(state):
                        candidate.transition_to(CandidateStatus.NORMALIZED)
                        candidate.transition_to(CandidateStatus.PLAUSIBLE)
                        candidate.transition_to(CandidateStatus.PRIORITIZED)
                        candidate.transition_to(CandidateStatus.CONFIRMED)
                        state.candidates.append(candidate)
                self._trace(state, round_plan)

            state.current_phase = Phase.DEEPEN
            for candidate in state.top_candidates(limit=state.budget.max_deepen_targets):
                for analyst in self.analysts:
                    evidence, findings, uncertainties = analyst.run(state, candidate)
                    state.evidence.extend(evidence)
                    state.findings.extend(findings)
                    state.uncertainties.extend(uncertainties)
            self._trace(state, "deepened top candidates")

            state.current_phase = Phase.CHALLENGE
            evidence_review = self.evidence_judge(state)
            coverage_review = self.coverage_judge(state)
            challenge_review = self.challenger(state)
            state.review_decisions.extend(
                [review for review in [evidence_review, coverage_review, challenge_review] if review is not None]
            )
            self._trace(state, "completed challenge phase")

            state.current_phase = Phase.DECIDE
            stop_decision = self.stop_judge.run(state)
            state.gap_tickets = stop_decision.gap_tickets
            self._trace(state, stop_decision.verdict.value)
            if stop_decision.verdict == StopVerdict.STOP:
                state.current_phase = Phase.STOP
                break

            state.carry_forward_context = self.compactor.compact(state)
            state.round_index += 1

        if state.current_phase != Phase.STOP:
            state.current_phase = Phase.STOP

        self.store.save_state(state)
        for trace in state.traces:
            self.store.append_trace(state.run_id, trace)
        return state

    def _trace(self, state: RunState, planner_output: str) -> None:
        trace = RunTrace(
            round_index=state.round_index,
            phase=state.current_phase,
            planner_output=planner_output,
            dispatched_tasks=[],
            new_candidates=[candidate.name for candidate in state.candidates],
            new_findings=[finding.finding_id for finding in state.findings],
            review_decisions=[decision.judge_type for decision in state.review_decisions],
            stop_or_continue=state.current_phase.value,
        )
        state.traces.append(trace)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_controller.py -v`
Expected: PASS with `1 passed`

- [ ] **Step 5: Commit the harness loop**

```bash
git add src/jingyantai/runtime/controller.py tests/test_controller.py
git commit -m "feat: add phase-driven harness controller"
```

### Task 8: Add Report Synthesis, Citation Pass, And The Deepagents Role Adapter

**Files:**
- Create: `src/jingyantai/runtime/reporting.py`
- Create: `src/jingyantai/agents/deepagents_adapter.py`
- Create: `src/jingyantai/agents/roles.py`
- Create: `tests/test_reporting.py`
- Create: `tests/test_deepagents_adapter.py`

- [ ] **Step 1: Write the failing reporting and adapter tests**

```python
# tests/test_reporting.py
from jingyantai.domain.models import Candidate, Evidence, FinalReport, Finding, RunState, BudgetPolicy
from jingyantai.domain.phases import CandidateStatus, Phase
from jingyantai.runtime.reporting import CitationAgent, Synthesizer


def test_synthesizer_and_citation_agent_build_cited_report():
    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.STOP,
        budget=BudgetPolicy(max_rounds=4, max_active_candidates=8, max_deepen_targets=3, max_external_fetches=30, max_run_duration_minutes=20),
    )
    state.candidates.append(
        Candidate(candidate_id="a", name="Aider", canonical_url="https://aider.chat", status=CandidateStatus.CONFIRMED, relevance_score=0.93, why_candidate="terminal coding agent")
    )
    state.evidence.append(
        Evidence(evidence_id="e1", subject_id="a", claim="Aider runs in the terminal", source_url="https://aider.chat", source_type="official", snippet="AI pair programmer in your terminal", captured_at="2026-04-01", freshness_score=0.95, confidence=0.95)
    )
    state.findings.append(
        Finding(finding_id="f1", subject_id="a", dimension="workflow", summary="Aider overlaps with Claude Code in terminal workflow.", evidence_ids=["e1"], confidence=0.95)
    )

    draft = Synthesizer().run(state)
    final = CitationAgent().run(state, draft)

    assert final.confirmed_competitors == ["Aider"]
    assert final.citations["Aider"] == ["https://aider.chat"]
```

```python
# tests/test_deepagents_adapter.py
from jingyantai.agents.deepagents_adapter import DeepagentsRoleAdapter
from jingyantai.domain.models import ResearchBrief


def test_deepagents_adapter_maps_runner_payload_to_model():
    def fake_runner(system_prompt: str, payload: dict) -> dict:
        assert "Initializer" in system_prompt
        assert payload["target"] == "Claude Code"
        return {
            "target": "Claude Code",
            "product_type": "coding-agent",
            "competitor_definition": "Direct competitors are terminal-native coding agents.",
            "required_dimensions": ["positioning", "workflow"],
            "stop_policy": "Stop after enough covered competitors.",
        }

    adapter = DeepagentsRoleAdapter(role_prompt="You are the Initializer.", runner=fake_runner)
    result = adapter.run({"target": "Claude Code"}, ResearchBrief)

    assert result.target == "Claude Code"
    assert result.product_type == "coding-agent"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reporting.py tests/test_deepagents_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement report generation and deepagents adapter**

```python
# src/jingyantai/runtime/reporting.py
from __future__ import annotations

from jingyantai.domain.models import FinalReport, RunState
from jingyantai.domain.phases import CandidateStatus


class Synthesizer:
    def run(self, state: RunState) -> FinalReport:
        confirmed = [candidate for candidate in state.candidates if candidate.status == CandidateStatus.CONFIRMED]
        return FinalReport(
            target_summary=f"Competitive landscape for {state.target}",
            confirmed_competitors=[candidate.name for candidate in confirmed],
            rejected_candidates=[candidate.name for candidate in state.candidates if candidate.status == CandidateStatus.REJECTED],
            comparison_matrix=[
                {"candidate": candidate.name, "url": candidate.canonical_url}
                for candidate in confirmed
            ],
            key_uncertainties=[item.statement for item in state.uncertainties],
            citations={},
        )


class CitationAgent:
    def run(self, state: RunState, draft: FinalReport) -> FinalReport:
        citations: dict[str, list[str]] = {}
        for candidate in state.candidates:
            citations[candidate.name] = sorted(
                {
                    evidence.source_url
                    for evidence in state.evidence
                    if evidence.subject_id == candidate.candidate_id
                }
            )
        draft.citations = citations
        return draft
```

```python
# src/jingyantai/agents/deepagents_adapter.py
from __future__ import annotations

from typing import Any, Type

from pydantic import BaseModel


class DeepagentsRoleAdapter:
    def __init__(self, role_prompt: str, runner) -> None:
        self.role_prompt = role_prompt
        self.runner = runner

    def run(self, payload: dict[str, Any], model_type: Type[BaseModel]):
        result = self.runner(self.role_prompt, payload)
        return model_type.model_validate(result)
```

```python
# src/jingyantai/agents/roles.py
from __future__ import annotations

from jingyantai.domain.models import Candidate, Evidence, Finding, ResearchBrief, RunCharter, UncertaintyItem
from jingyantai.domain.phases import CandidateStatus
from jingyantai.tools.research_tools import ResearchTools


class InitializerRole:
    def run(self, target: str) -> tuple[ResearchBrief, RunCharter]:
        return (
            ResearchBrief(
                target=target,
                product_type="coding-agent",
                competitor_definition="Direct competitors are terminal-native coding agents for software engineers.",
                required_dimensions=["positioning", "workflow", "core capabilities", "pricing or access", "community / ecosystem signal"],
                stop_policy="Stop after at least 3 confirmed competitors meet evidence and coverage gates.",
            ),
            RunCharter(
                mission=f"Research direct competitors for {target}",
                scope=["terminal-native coding agents", "developer workflows", "pricing and ecosystem signals"],
                non_goals=["broad foundation-model vendor comparison"],
                success_criteria=["3 confirmed competitors", "minimum evidence gate met", "challenger has no blocking objection"],
                research_agenda=["expand candidates", "deepen evidence", "challenge fit", "stop when covered"],
            ),
        )


class LeadResearcherRole:
    def run(self, state) -> str:
        if state.gap_tickets:
            return f"Address gap tickets for: {', '.join(ticket.target_scope for ticket in state.gap_tickets)}"
        return f"Expand and deepen direct competitors for {state.target}"


class ScoutRole:
    def __init__(self, tools: ResearchTools, hypothesis: str) -> None:
        self.tools = tools
        self.hypothesis = hypothesis

    def run(self, state) -> list[Candidate]:
        raw_candidates = self.tools.search_competitor_candidates(state.target, self.hypothesis, ["web", "github"])
        return [
            Candidate(
                candidate_id=item["name"].lower().replace(" ", "-"),
                name=item["name"],
                canonical_url=item["canonical_url"],
                status=CandidateStatus.DISCOVERED,
                relevance_score=0.75,
                why_candidate=item["why_candidate"],
            )
            for item in raw_candidates
        ]


class AnalystRole:
    def __init__(self, tools: ResearchTools, dimension: str) -> None:
        self.tools = tools
        self.dimension = dimension

    def run(self, state, candidate: Candidate) -> tuple[list[Evidence], list[Finding], list[UncertaintyItem]]:
        bundle = self.tools.build_evidence_bundle(candidate.name, candidate.canonical_url)
        if self.dimension == "positioning":
            selected = bundle["positioning"]
        elif self.dimension == "workflow":
            selected = bundle["workflow"]
        else:
            selected = bundle["pricing_or_access"]
        evidence = Evidence(
            evidence_id=f"e-{candidate.candidate_id}-{self.dimension}",
            subject_id=candidate.candidate_id,
            claim=selected["summary"][:160],
            source_url=selected["source_url"],
            source_type="official",
            snippet=selected["summary"][:280],
            captured_at="2026-04-01",
            freshness_score=0.9,
            confidence=0.85,
        )
        finding = Finding(
            finding_id=f"f-{candidate.candidate_id}-{self.dimension}",
            subject_id=candidate.candidate_id,
            dimension=self.dimension,
            summary=selected["summary"][:200],
            evidence_ids=[evidence.evidence_id],
            confidence=0.85,
        )
        uncertainty = UncertaintyItem(
            statement=f"Need more detail for {candidate.name} on {self.dimension}",
            impact="medium",
            resolvability="search-more",
            required_evidence=f"Additional {self.dimension} sources",
            owner_role="analyst",
        )
        return [evidence], [finding], [uncertainty]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reporting.py tests/test_deepagents_adapter.py -v`
Expected: PASS with `2 passed`

- [ ] **Step 5: Commit reporting and adapter work**

```bash
git add src/jingyantai/runtime/reporting.py src/jingyantai/agents/deepagents_adapter.py src/jingyantai/agents/roles.py tests/test_reporting.py tests/test_deepagents_adapter.py
git commit -m "feat: add report synthesis and deepagents adapter"
```

### Task 9: Wire Settings And CLI For A Real End-To-End Local Run

**Files:**
- Create: `src/jingyantai/config.py`
- Modify: `src/jingyantai/cli.py`
- Modify: `README.md`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write the failing CLI integration test**

```python
# tests/test_cli.py
from typer.testing import CliRunner

from jingyantai.cli import app


def test_run_command_emits_run_id_target_and_confirmed_competitors(monkeypatch, tmp_path):
    from jingyantai.domain.models import BudgetPolicy, FinalReport, RunState
    from jingyantai.domain.phases import Phase

    class FakeController:
        def run(self, target: str, budget: BudgetPolicy):
            state = RunState(run_id="run-test", target=target, current_phase=Phase.STOP, budget=budget)
            state.final_report = FinalReport(
                target_summary="Competitive landscape for Claude Code",
                confirmed_competitors=["Aider", "OpenAI Codex CLI", "OpenCode"],
                rejected_candidates=[],
                comparison_matrix=[],
                key_uncertainties=[],
                citations={"Aider": ["https://aider.chat"]},
            )
            return state

    monkeypatch.setattr("jingyantai.cli.build_controller", lambda settings: FakeController())
    runner = CliRunner()

    result = runner.invoke(app, ["run", "Claude Code", "--runs-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert "run-test" in result.stdout
    assert "Claude Code" in result.stdout
    assert "Aider" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL with `AttributeError: module 'jingyantai.cli' has no attribute 'build_controller'`

- [ ] **Step 3: Implement settings and CLI wiring**

```python
# src/jingyantai/config.py
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    model_provider: str = "anthropic"
    model_name: str = "claude-3-7-sonnet-latest"
    tavily_api_key: str = ""
    github_token: str = ""
    runs_dir: Path = Path("./runs")
```

```python
# src/jingyantai/cli.py
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from jingyantai.agents.roles import AnalystRole, InitializerRole, LeadResearcherRole, ScoutRole
from jingyantai.config import Settings
from jingyantai.domain.models import BudgetPolicy
from jingyantai.runtime.compactor import ContextCompactor
from jingyantai.runtime.controller import HarnessController
from jingyantai.runtime.judges import Challenger, CoverageJudge, EvidenceJudge, StopJudge
from jingyantai.runtime.reporting import CitationAgent, Synthesizer
from jingyantai.storage.run_store import FileRunStore
from jingyantai.tools.github_signals import GitHubSignals
from jingyantai.tools.page_extract import HttpPageExtractor
from jingyantai.tools.research_tools import ResearchTools
from jingyantai.tools.web_search import TavilySearchClient

app = typer.Typer(name="jingyantai", no_args_is_help=True)
console = Console()


def build_controller(settings: Settings):
    tools = ResearchTools(
        search_client=TavilySearchClient(settings.tavily_api_key),
        page_extractor=HttpPageExtractor(),
        github_signals=GitHubSignals(settings.github_token or None),
    )
    return HarnessController(
        store=FileRunStore(settings.runs_dir),
        initializer=InitializerRole(),
        lead_researcher=LeadResearcherRole(),
        scouts=[
            ScoutRole(tools, "terminal coding agent"),
            ScoutRole(tools, "repo-aware coding agent"),
            ScoutRole(tools, "developer CLI agent"),
        ],
        analysts=[
            AnalystRole(tools, "positioning"),
            AnalystRole(tools, "workflow"),
            AnalystRole(tools, "pricing or access"),
        ],
        compactor=ContextCompactor(),
        evidence_judge=EvidenceJudge(),
        coverage_judge=CoverageJudge(["positioning", "workflow", "pricing or access"]),
        challenger=Challenger(),
        stop_judge=StopJudge(["positioning", "workflow", "pricing or access"]),
    )


@app.command()
def run(
    target: str,
    runs_dir: Path | None = typer.Option(default=None, help="Override run artifact directory."),
) -> None:
    settings = Settings()
    if runs_dir is not None:
        settings.runs_dir = runs_dir
    controller = build_controller(settings)
    state = controller.run(
        target=target,
        budget=BudgetPolicy(
            max_rounds=4,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        ),
    )
    if state.final_report is None:
        draft = Synthesizer().run(state)
        state.final_report = CitationAgent().run(state, draft)
    console.print(f"run_id={state.run_id}")
    console.print(f"target={state.target}")
    console.print(f"confirmed={', '.join(state.final_report.confirmed_competitors)}")


@app.callback()
def main() -> None:
    """竞研台 CLI."""
```

```markdown
# README.md

# 竞研台

面向小团队的长程竞品研究 Harness。

## Setup

```bash
pip install -e .[dev]
cp .env.example .env
```

## Run

```bash
jingyantai run "Claude Code"
```

## MVP Properties

- Long-running harness with explicit phases
- Generator/evaluator separation
- File-backed run artifacts
- Cited final report
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py -v`
Expected: PASS with `1 passed`

- [ ] **Step 5: Commit the runnable CLI surface**

```bash
git add src/jingyantai/config.py src/jingyantai/cli.py README.md tests/test_cli.py
git commit -m "feat: add settings and CLI entrypoint"
```

## Self-Review Checklist

### Spec coverage

- `Harness Controller`: covered in Task 7
- `Run State Store`: covered in Task 3
- `Initializer`, `Lead Researcher`, `Scout`, `Analyst` contracts: covered in Task 5
- `Evidence Judge`, `Coverage Judge`, `Challenger`, `Stop Judge`: covered in Task 6
- `Context Compactor`: covered in Task 6
- `Citation Pass` and `Synthesizer`: covered in Task 8
- `deepagents`-based role execution: covered in Task 8
- `CLI and local execution`: covered in Task 9

### Gaps intentionally left for a later plan

- Cross-run memory
- Scheduled reruns
- Alerts and watchlists
- Multi-tenant collaboration workflows

### Placeholder scan

- No `TBD`, `TODO`, or “implement later” placeholders remain in the task steps.

### Type consistency

- `StopDecision` is the only type that can carry a `StopVerdict`.
- `Candidate.transition_to()` is the only mechanism used for candidate state changes.
- The controller always stores a `RunState`, never a raw dict.
