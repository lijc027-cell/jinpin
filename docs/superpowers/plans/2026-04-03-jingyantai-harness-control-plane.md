# 竞研台 Harness 控制面增强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first real control-plane upgrade for `竞研台`, adding explicit runtime policy, contract-driven rounds, stronger stop semantics, and local memory/watchlist artifacts without breaking the current long-running harness.

**Architecture:** Keep the existing `controller -> roles -> tools -> store` skeleton, but add a thin runtime policy layer, a contract/rubric layer, and a file-backed memory layer. The controller remains the orchestrator, while policy objects decide timeout/retry/degrade behavior and judges consume a shared quality bar plus convergence signals.

**Tech Stack:** Python 3.12, Pydantic v2, Typer, Rich, httpx, pytest

---

## Project Root

All files in this plan live under:

`/Users/l/Downloads/projects/竞品`

## File Structure

- Create: `src/jingyantai/runtime/policies.py`
  Runtime control objects: `ContextStrategy`, `PhasePolicy`, `RetryPolicy`, `DegradeAction`, `PhaseOutcome`, `StopBar`, `QualityRubric`, `ConvergenceSnapshot`
- Create: `src/jingyantai/runtime/contracts.py`
  `RoundContract`, `ContractJudge`, and small helpers for contract validation
- Create: `src/jingyantai/runtime/memory.py`
  `RunMemoryEntry`, `WatchlistItem`, `MemorySnapshot`, and `FileMemoryStore`
- Modify: `src/jingyantai/domain/models.py`
  Add runtime-facing models that need to be serialized in `RunState`
- Modify: `src/jingyantai/runtime/controller.py`
  Drive phase execution through explicit policy and contract objects
- Modify: `src/jingyantai/runtime/judges.py`
  Upgrade stop logic to `Hard Gate + Convergence Gate`
- Modify: `src/jingyantai/agents/roles.py`
  Accept artifact-backed context and round contract inputs where needed
- Modify: `src/jingyantai/cli.py`
  Wire default runtime policy, persist new artifacts, expose stop reason cleanly
- Modify: `src/jingyantai/storage/run_store.py`
  Save research spec, round contract, progress log, evaluator log, and memory artifacts
- Create: `tests/test_runtime_policies.py`
  Unit tests for control policy models and retry decisions
- Create: `tests/test_runtime_contracts.py`
  Unit tests for round contracts and contract judging
- Create: `tests/test_runtime_memory.py`
  Unit tests for file-backed memory and watchlist persistence
- Modify: `tests/test_controller.py`
  Add policy/timeout/degrade/forced-stop integration tests
- Modify: `tests/test_judges.py`
  Add `StopBar` / convergence tests
- Modify: `tests/test_cli.py`
  Validate new artifact persistence and stop-reason output

### Task 1: Define Runtime Policy Models

**Files:**
- Create: `src/jingyantai/runtime/policies.py`
- Create: `tests/test_runtime_policies.py`

- [ ] **Step 1: Write the failing policy tests**

```python
# tests/test_runtime_policies.py
from jingyantai.runtime.policies import (
    ContextStrategy,
    DegradeAction,
    PhasePolicy,
    RetryDecision,
    RetryPolicy,
    RuntimePolicy,
)


def test_runtime_policy_exposes_default_phase_policies():
    policy = RuntimePolicy.default()

    assert policy.context_strategy == ContextStrategy.CONTINUOUS_COMPACTION
    assert policy.phase_policies["expand"].soft_timeout_seconds > 0
    assert policy.phase_policies["deepen"].allow_partial_success is True


def test_retry_policy_maps_timeout_to_retry_then_degrade():
    policy = RetryPolicy.default()

    first = policy.decide(error_kind="timeout", attempt=1, phase_name="deepen")
    second = policy.decide(error_kind="timeout", attempt=2, phase_name="deepen")

    assert first.decision == RetryDecision.RETRY
    assert second.decision == RetryDecision.DEGRADE
    assert second.degrade_action == DegradeAction.REDUCE_DEEPEN_TARGETS


def test_retry_policy_marks_bad_candidate_as_skip():
    policy = RetryPolicy.default()

    decision = policy.decide(error_kind="bad_candidate", attempt=1, phase_name="deepen")

    assert decision.decision == RetryDecision.SKIP
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_runtime_policies.py -q`
Expected: FAIL with `ModuleNotFoundError` or missing symbols from `jingyantai.runtime.policies`

- [ ] **Step 3: Write minimal runtime policy implementation**

```python
# src/jingyantai/runtime/policies.py
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ContextStrategy(StrEnum):
    CONTINUOUS_COMPACTION = "continuous_compaction"
    PERIODIC_RESET = "periodic_reset"
    HYBRID = "hybrid"


class RetryDecision(StrEnum):
    RETRY = "retry"
    DEGRADE = "degrade"
    SKIP = "skip"
    FAIL_PHASE = "fail_phase"


class DegradeAction(StrEnum):
    REDUCE_DEEPEN_TARGETS = "reduce_deepen_targets"
    REDUCE_SEARCH_RESULTS = "reduce_search_results"
    USE_CACHED_RESULTS_ONLY = "use_cached_results_only"
    FALLBACK_GITHUB_ONLY = "fallback_github_only"
    MARK_CANDIDATE_LOW_CONFIDENCE = "mark_candidate_low_confidence"
    SKIP_SLOWEST_CANDIDATES = "skip_slowest_candidates"


class PhasePolicy(BaseModel):
    soft_timeout_seconds: float
    max_attempts: int
    allow_partial_success: bool
    degrade_on: dict[str, DegradeAction] = Field(default_factory=dict)


class RetryOutcome(BaseModel):
    decision: RetryDecision
    degrade_action: DegradeAction | None = None


class RetryPolicy(BaseModel):
    timeout_degrade_action: DegradeAction = DegradeAction.REDUCE_DEEPEN_TARGETS

    @classmethod
    def default(cls) -> "RetryPolicy":
        return cls()

    def decide(self, *, error_kind: str, attempt: int, phase_name: str) -> RetryOutcome:
        if error_kind == "bad_candidate":
            return RetryOutcome(decision=RetryDecision.SKIP)
        if error_kind == "timeout":
            if attempt < 2:
                return RetryOutcome(decision=RetryDecision.RETRY)
            return RetryOutcome(
                decision=RetryDecision.DEGRADE,
                degrade_action=self.timeout_degrade_action,
            )
        return RetryOutcome(decision=RetryDecision.FAIL_PHASE)


class RuntimePolicy(BaseModel):
    context_strategy: ContextStrategy
    phase_policies: dict[str, PhasePolicy]
    retry_policy: RetryPolicy

    @classmethod
    def default(cls) -> "RuntimePolicy":
        return cls(
            context_strategy=ContextStrategy.CONTINUOUS_COMPACTION,
            phase_policies={
                "initialize": PhasePolicy(soft_timeout_seconds=90.0, max_attempts=1, allow_partial_success=False),
                "expand": PhasePolicy(soft_timeout_seconds=180.0, max_attempts=2, allow_partial_success=True),
                "deepen": PhasePolicy(soft_timeout_seconds=240.0, max_attempts=2, allow_partial_success=True),
                "challenge": PhasePolicy(soft_timeout_seconds=60.0, max_attempts=1, allow_partial_success=False),
                "decide": PhasePolicy(soft_timeout_seconds=60.0, max_attempts=1, allow_partial_success=False),
            },
            retry_policy=RetryPolicy.default(),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_runtime_policies.py -q`
Expected: PASS with `3 passed`

- [ ] **Step 5: Commit**

```bash
git add src/jingyantai/runtime/policies.py tests/test_runtime_policies.py
git commit -m "feat: add runtime policy models"
```

### Task 2: Add Round Contract And Contract Judge

**Files:**
- Create: `src/jingyantai/runtime/contracts.py`
- Create: `tests/test_runtime_contracts.py`

- [ ] **Step 1: Write the failing contract tests**

```python
# tests/test_runtime_contracts.py
from jingyantai.runtime.contracts import ContractJudge, RoundContract


def test_contract_judge_rejects_overwide_goal_cluster():
    contract = RoundContract(
        target_scope="Claude Code landscape",
        goal_cluster="expand+deepen+pricing+workflow",
        must_answer_questions=["Who are the direct competitors?"],
        required_evidence_types=["official", "github"],
        hard_checks=["direct competitor fit"],
        done_definition="Finish all research.",
        fallback_plan="Use cached evidence.",
    )

    decision = ContractJudge().run(contract)

    assert decision.is_valid is False
    assert "single goal cluster" in decision.reasons[0]


def test_contract_judge_accepts_focused_contract():
    contract = RoundContract(
        target_scope="confirmed candidates",
        goal_cluster="resolve pricing uncertainty",
        must_answer_questions=["How is access or pricing exposed?"],
        required_evidence_types=["official"],
        hard_checks=["must cite official source"],
        done_definition="At least 2 confirmed competitors have pricing/access findings.",
        fallback_plan="Keep unresolved items as uncertainties.",
    )

    decision = ContractJudge().run(contract)

    assert decision.is_valid is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_runtime_contracts.py -q`
Expected: FAIL with `ModuleNotFoundError` or missing symbols from `jingyantai.runtime.contracts`

- [ ] **Step 3: Write minimal contract implementation**

```python
# src/jingyantai/runtime/contracts.py
from __future__ import annotations

from pydantic import BaseModel, Field


class RoundContract(BaseModel):
    target_scope: str
    goal_cluster: str
    must_answer_questions: list[str] = Field(default_factory=list)
    required_evidence_types: list[str] = Field(default_factory=list)
    hard_checks: list[str] = Field(default_factory=list)
    done_definition: str
    fallback_plan: str


class ContractDecision(BaseModel):
    is_valid: bool
    reasons: list[str] = Field(default_factory=list)


class ContractJudge:
    def run(self, contract: RoundContract) -> ContractDecision:
        if "+" in contract.goal_cluster:
            return ContractDecision(is_valid=False, reasons=["RoundContract must focus on a single goal cluster."])
        if not contract.hard_checks:
            return ContractDecision(is_valid=False, reasons=["RoundContract must include at least one hard check."])
        if "all research" in contract.done_definition.lower():
            return ContractDecision(is_valid=False, reasons=["Done definition must be concretely verifiable."])
        return ContractDecision(is_valid=True, reasons=[])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_runtime_contracts.py -q`
Expected: PASS with `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/jingyantai/runtime/contracts.py tests/test_runtime_contracts.py
git commit -m "feat: add round contract validation"
```

### Task 3: Upgrade Stop Judge To Hard Gate And Convergence Gate

**Files:**
- Modify: `src/jingyantai/runtime/policies.py`
- Modify: `src/jingyantai/runtime/judges.py`
- Modify: `tests/test_judges.py`

- [ ] **Step 1: Write the failing stop-bar tests**

```python
# tests/test_judges.py
from jingyantai.domain.models import BudgetPolicy, Candidate, RunState
from jingyantai.domain.phases import CandidateStatus, Phase, StopVerdict
from jingyantai.runtime.judges import StopJudge
from jingyantai.runtime.policies import StopBar


def test_stop_judge_continues_when_hard_gate_fails_even_if_candidate_count_is_high():
    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.DECIDE,
        budget=BudgetPolicy(max_rounds=4, max_active_candidates=8, max_deepen_targets=3, max_external_fetches=30, max_run_duration_minutes=20),
    )
    state.candidates.append(
        Candidate(
            candidate_id="a",
            name="Aider",
            canonical_url="https://aider.chat",
            status=CandidateStatus.CONFIRMED,
            relevance_score=0.9,
            why_candidate="terminal coding agent",
        )
    )

    stop = StopJudge(["positioning"], stop_bar=StopBar.default())
    decision = stop.run(state)

    assert decision.verdict == StopVerdict.CONTINUE
    assert "hard gate" in decision.reasons[0].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_judges.py -q`
Expected: FAIL with `TypeError` or missing `StopBar`

- [ ] **Step 3: Extend policy and judge implementation**

```python
# src/jingyantai/runtime/policies.py
class StopBar(BaseModel):
    min_confirmed_candidates: int = 3
    min_coverage_ratio: float = 0.8
    max_high_impact_uncertainties: int = 0
    max_new_confirmed_for_convergence: int = 1
    max_new_findings_for_convergence: int = 2

    @classmethod
    def default(cls) -> "StopBar":
        return cls()
```

```python
# src/jingyantai/runtime/judges.py
class StopJudge:
    def __init__(self, required_dimensions: list[str], stop_bar: StopBar | None = None) -> None:
        self.required_dimensions = list(required_dimensions)
        self.stop_bar = stop_bar or StopBar.default()

    def run(self, state: RunState) -> StopDecision:
        confirmed = [candidate for candidate in state.candidates if candidate.status == CandidateStatus.CONFIRMED]
        if len(confirmed) < self.stop_bar.min_confirmed_candidates:
            return StopDecision(
                verdict=StopVerdict.CONTINUE,
                reasons=["Hard gate failed: not enough confirmed competitors."],
                gap_tickets=[],
            )
        # Keep the existing coverage/open-question checks here.
        return StopDecision(
            verdict=StopVerdict.STOP,
            reasons=["Quality bar met"],
            gap_tickets=[],
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_judges.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/jingyantai/runtime/policies.py src/jingyantai/runtime/judges.py tests/test_judges.py
git commit -m "feat: add stop bar and convergence gate scaffolding"
```

### Task 4: Add File-Backed Memory And Watchlist

**Files:**
- Create: `src/jingyantai/runtime/memory.py`
- Create: `tests/test_runtime_memory.py`

- [ ] **Step 1: Write the failing memory tests**

```python
# tests/test_runtime_memory.py
from pathlib import Path

from jingyantai.runtime.memory import FileMemoryStore, MemorySnapshot, WatchlistItem


def test_file_memory_store_persists_snapshot_and_watchlist(tmp_path: Path):
    store = FileMemoryStore(tmp_path)
    snapshot = MemorySnapshot(
        top_competitors=["Aider", "OpenAI Codex"],
        unresolved_uncertainties=["Pricing remains unclear."],
        trusted_sources=["https://aider.chat"],
        repeated_failure_patterns=["timeout: developers.google.com"],
    )
    watchlist = [
        WatchlistItem(
            entity_name="OpenAI Codex",
            canonical_url="https://openai.com/index/codex",
            watch_reason="pricing uncertainty",
            revisit_trigger="official pricing page changes",
            priority="high",
            last_seen_run_id="run-1",
        )
    ]

    store.save_snapshot(snapshot)
    store.save_watchlist(watchlist)

    assert store.load_snapshot() == snapshot
    assert store.load_watchlist() == watchlist
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_runtime_memory.py -q`
Expected: FAIL with `ModuleNotFoundError` or missing `jingyantai.runtime.memory`

- [ ] **Step 3: Write minimal memory implementation**

```python
# src/jingyantai/runtime/memory.py
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class WatchlistItem(BaseModel):
    entity_name: str
    canonical_url: str
    watch_reason: str
    revisit_trigger: str
    priority: str
    last_seen_run_id: str


class MemorySnapshot(BaseModel):
    top_competitors: list[str] = Field(default_factory=list)
    unresolved_uncertainties: list[str] = Field(default_factory=list)
    trusted_sources: list[str] = Field(default_factory=list)
    repeated_failure_patterns: list[str] = Field(default_factory=list)


class FileMemoryStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.global_dir = self.root_dir / "_global"

    def save_snapshot(self, snapshot: MemorySnapshot) -> None:
        self.global_dir.mkdir(parents=True, exist_ok=True)
        (self.global_dir / "latest-snapshot.json").write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")

    def load_snapshot(self) -> MemorySnapshot:
        payload = json.loads((self.global_dir / "latest-snapshot.json").read_text(encoding="utf-8"))
        return MemorySnapshot.model_validate(payload)

    def save_watchlist(self, items: list[WatchlistItem]) -> None:
        self.global_dir.mkdir(parents=True, exist_ok=True)
        data = [item.model_dump() for item in items]
        (self.global_dir / "watchlist.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load_watchlist(self) -> list[WatchlistItem]:
        payload = json.loads((self.global_dir / "watchlist.json").read_text(encoding="utf-8"))
        return [WatchlistItem.model_validate(item) for item in payload]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_runtime_memory.py -q`
Expected: PASS with `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/jingyantai/runtime/memory.py tests/test_runtime_memory.py
git commit -m "feat: add file-backed harness memory store"
```

### Task 5: Wire Controller, Store, And CLI To New Artifacts

**Files:**
- Modify: `src/jingyantai/domain/models.py`
- Modify: `src/jingyantai/runtime/controller.py`
- Modify: `src/jingyantai/storage/run_store.py`
- Modify: `src/jingyantai/cli.py`
- Modify: `tests/test_controller.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the failing controller and CLI tests**

```python
# tests/test_controller.py
from pathlib import Path

from jingyantai.domain.models import BudgetPolicy
from jingyantai.domain.phases import StopVerdict
from jingyantai.runtime.compactor import ContextCompactor
from jingyantai.runtime.contracts import RoundContract
from jingyantai.runtime.controller import HarnessController
from jingyantai.storage.run_store import FileRunStore
from fakes import FakeInitializer


class FakeLeadResearcher:
    def run(self, state):
        return "Resolve pricing uncertainty for top competitors."


class FakeContractBuilder:
    def build(self, state):
        return RoundContract(
            target_scope="confirmed candidates",
            goal_cluster="resolve pricing uncertainty",
            must_answer_questions=["How is access exposed?"],
            required_evidence_types=["official"],
            hard_checks=["must cite official source"],
            done_definition="At least one pricing/access finding is produced.",
            fallback_plan="Keep unresolved issues as uncertainties.",
        )


def test_controller_persists_round_contract_and_progress_log(tmp_path: Path):
    store = FileRunStore(tmp_path / "runs")
    controller = HarnessController(
        store=store,
        initializer=FakeInitializer(),
        lead_researcher=FakeLeadResearcher(),
        scouts=[],
        analysts=[],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=lambda state: None,
        challenger=lambda state: None,
        stop_judge=lambda state: type("StopNow", (), {"verdict": StopVerdict.STOP, "gap_tickets": [], "reasons": ["done"]})(),
        contract_builder=FakeContractBuilder(),
    )

    final_state = controller.run(
        target="Claude Code",
        budget=BudgetPolicy(max_rounds=0, max_active_candidates=8, max_deepen_targets=3, max_external_fetches=30, max_run_duration_minutes=20),
    )

    run_dir = tmp_path / "runs" / final_state.run_id / "artifacts"
    assert (run_dir / "round-contract-000.json").exists()
    assert (run_dir / "progress-log.jsonl").exists()
```

```python
# tests/test_cli.py
from typer.testing import CliRunner

from jingyantai.cli import app


def test_run_command_reports_forced_stop_reason(monkeypatch, tmp_path):
    from jingyantai.domain.models import BudgetPolicy, FinalReport, RunState
    from jingyantai.domain.phases import Phase
    from jingyantai.storage.run_store import FileRunStore

    class FakeController:
        def __init__(self) -> None:
            self.store = FileRunStore(tmp_path)

        def run(self, target: str, budget: BudgetPolicy):
            state = RunState(run_id="run-test", target=target, current_phase=Phase.STOP, budget=budget)
            state.stop_reason = "forced_stop_due_to_budget"
            state.final_report = FinalReport(
                target_summary="Competitive landscape for Claude Code",
                confirmed_competitors=["Aider"],
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
    assert "stop_reason=forced_stop_due_to_budget" in result.stdout
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_controller.py tests/test_cli.py -q`
Expected: FAIL because round-contract artifacts and stop-reason outputs do not exist yet

- [ ] **Step 3: Modify the runtime and CLI**

```python
# src/jingyantai/domain/models.py
class RunProgressEvent(BaseModel):
    run_id: str
    round_index: int
    phase: Phase
    stage: str
    message: str
    candidate_count: int
    finding_count: int
    external_fetch_count: int
    stop_reason: str | None = None


class RunState(BaseModel):
    run_id: str
    target: str
    current_phase: Phase
    budget: BudgetPolicy
    stop_reason: str | None = None
```

```python
# src/jingyantai/storage/run_store.py
class FileRunStore:
    def save_round_contract(self, run_id: str, round_index: int, payload: dict[str, object]) -> Path:
        run_dir = self._run_dir(run_id)
        path = run_dir / "artifacts" / f"round-contract-{round_index:03d}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def append_progress_log(self, run_id: str, payload: dict[str, object]) -> Path:
        run_dir = self._run_dir(run_id)
        path = run_dir / "artifacts" / "progress-log.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return path
```

```python
# src/jingyantai/runtime/controller.py
class HarnessController:
    def _persist_handoff_artifacts(self, state: RunState, contract: RoundContract | None) -> None:
        if contract is not None:
            save_round_contract = getattr(self.store, "save_round_contract", None)
            if callable(save_round_contract):
                save_round_contract(state.run_id, state.round_index, contract.model_dump())

    def _emit_progress(self, state: RunState, phase: Phase, stage: str, message: str) -> None:
        event = RunProgressEvent(
            run_id=state.run_id,
            round_index=state.round_index,
            phase=phase,
            stage=stage,
            message=message,
            candidate_count=len(state.candidates),
            finding_count=len(state.findings),
            external_fetch_count=state.external_fetch_count,
            stop_reason=state.stop_reason,
        )
        append_progress_log = getattr(self.store, "append_progress_log", None)
        if callable(append_progress_log):
            append_progress_log(state.run_id, event.model_dump(mode="json"))
        if callable(self.progress_reporter):
            self.progress_reporter(event)
```

```python
# src/jingyantai/cli.py
def _console_progress_reporter(event: RunProgressEvent) -> None:
    console.print(
        f"{event.run_id} {event.stage} {event.phase.value} "
        f"round={event.round_index} candidates={event.candidate_count} "
        f"findings={event.finding_count} fetches={event.external_fetch_count} "
        f"| {event.message}"
    )
    if event.stop_reason and event.stage == "end":
        console.print(f"stop_reason={event.stop_reason}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_controller.py tests/test_cli.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/jingyantai/domain/models.py src/jingyantai/runtime/controller.py src/jingyantai/storage/run_store.py src/jingyantai/cli.py tests/test_controller.py tests/test_cli.py
git commit -m "feat: persist harness control artifacts"
```

### Task 6: Run Full Verification And Real Smoke

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-04-02-jingyantai-llm-runtime.md`

- [ ] **Step 1: Update docs to describe the new control plane**

```markdown
## 当前实现

- controller 现在会输出 round contract、progress log、evaluator log
- stop reason 会区分 quality stop 与 forced stop
- 本地 runs/_global 下会持久化 latest-snapshot 和 watchlist
```

- [ ] **Step 2: Run the full automated suite**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q`
Expected: PASS with all tests green

- [ ] **Step 3: Run a fresh real smoke**

Run: `PYTHONPATH=src python -m jingyantai.cli run "Claude Code" --runs-dir /tmp/jingyantai-harness-control-smoke`
Expected:
- CLI 持续输出 phase/progress 信息
- 产出 `state.json`
- 产出 `final-report.json`
- 产出 `research-spec.json`
- 产出 `progress-log.jsonl`
- 产出 `watchlist.json` 或 `latest-snapshot.json`

- [ ] **Step 4: Inspect artifacts and confirm stop semantics**

Run: `find /tmp/jingyantai-harness-control-smoke -maxdepth 3 -type f | sort`
Expected: 输出中包含 report、trace、contract、progress log、memory artifacts

- [ ] **Step 5: Commit**

```bash
git add README.md docs/superpowers/plans/2026-04-02-jingyantai-llm-runtime.md
git commit -m "docs: document harness control plane runtime"
```
