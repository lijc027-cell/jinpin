# 竞研台 Phase 2 Agent 研究质量 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让竞研台的研究循环更像真正的 long-running agent：会围绕 gap ticket 聚焦下一轮、会更深地利用历史 memory/watchlist、会生成更精确的 gap ticket，并且只在质量 bar 真正满足时停止。

**Architecture:** 本阶段不碰上线层，也不重写 controller 主循环。变化集中在 3 个点：`prompts.py` 增强 calibration 和“下一轮聚焦”约束，`roles.py` 增加更深的 execution-focus payload，`judges.py` 把 generic gap ticket 和宽松 stop 条件收紧成更细的 candidate/dimension 级判断。

**Tech Stack:** Python, pytest, Pydantic, 现有 `prompts / roles / judges / controller`

---

## 范围与非范围

本计划只覆盖 `B`：

- 更强的 prompt calibration
- 更深的 memory/watchlist 注入
- 更准的 gap ticket
- 更严格的 stop 条件

明确不在本计划内：

- 候选来源质量
- 报告格式增强
- Web/API/队列/恢复运行

## 文件结构

- Modify: `src/jingyantai/agents/prompts.py`
  - 强化 Lead/Scout/Analyst 的 calibration 规则与 next-round 聚焦约束
- Modify: `src/jingyantai/agents/roles.py`
  - 给 Lead/Scout/Analyst 注入 `execution_focus` 这类更深的 memory/watchlist/gap ticket 摘要
- Modify: `src/jingyantai/runtime/judges.py`
  - 收紧 stop 条件并生成更细粒度 gap ticket
- Test: `tests/test_prompts.py`
- Test: `tests/test_roles_llm.py`
- Test: `tests/test_judges.py`
- Test: `tests/test_controller.py`

## Task 1: Prompt Calibration 与 Execution Focus Payload

**Files:**
- Modify: `src/jingyantai/agents/prompts.py`
- Modify: `src/jingyantai/agents/roles.py`
- Test: `tests/test_prompts.py`
- Test: `tests/test_roles_llm.py`

- [ ] **Step 1: 写失败测试，锁定 prompt 必须显式约束“围绕 gap ticket 聚焦本轮”**

```python
def test_lead_researcher_prompt_requires_gap_ticket_driven_next_round_plan():
    prompt = get_role_prompt("lead_researcher", rubric=QualityRubric.default())

    assert "gap_tickets" in prompt
    assert "execution_focus" in prompt
    assert "Do not restate the entire mission" in prompt
    assert "Choose the smallest next step that can close a named gap" in prompt
```

- [ ] **Step 2: 写失败测试，锁定 scout/analyst prompt 的更强 calibration**

```python
def test_scout_and_analyst_prompts_include_positive_and_negative_calibration_examples():
    scout = get_role_prompt("scout_github", rubric=QualityRubric.default())
    analyst = get_role_prompt("analyst_workflow", rubric=QualityRubric.default())

    assert "Good pattern" in scout
    assert "Bad pattern" in scout
    assert "Prefer candidates that close a current gap ticket" in scout

    assert "Good pattern" in analyst
    assert "Bad pattern" in analyst
    assert "If execution_focus says this dimension is not the bottleneck" in analyst
```

- [ ] **Step 3: 写失败测试，锁定 roles 会把 execution focus 摘要传给模型层**

```python
def test_roles_pass_execution_focus_payload_to_adapter():
    adapter = StaticAdapter(LeadResearcherOutput(round_plan="Focus on pricing gap."))
    role = LeadResearcherRole(adapter=adapter)
    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.EXPAND,
        budget=_budget(),
        memory_snapshot={"top_competitors": ["Legacy One"], "repeated_failure_patterns": ["pricing loop"]},
        watchlist=[{"entity_name": "Legacy One", "watch_reason": "pricing gap", "priority": "high"}],
        gap_tickets=[
            GapTicket(
                gap_type="coverage",
                target_scope="Legacy One",
                blocking_reason="Missing dimensions: pricing or access",
                owner_role="analyst",
                acceptance_rule="Cover pricing with direct evidence.",
                deadline_round=1,
                priority=GapPriority.HIGH,
            )
        ],
    )

    role.run(state)

    assert adapter.calls[0][0]["execution_focus"]["priority_gaps"] == ["Legacy One: Missing dimensions: pricing or access"]
    assert adapter.calls[0][0]["execution_focus"]["watchlist_entities"] == ["Legacy One"]
    assert adapter.calls[0][0]["execution_focus"]["repeated_failures"] == ["pricing loop"]
```

- [ ] **Step 4: 运行失败测试**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  tests/test_prompts.py \
  tests/test_roles_llm.py -k "execution_focus or lead_researcher"
```

Expected:

```text
new prompt and role focus tests fail
```

- [ ] **Step 5: 实现最小 prompt 强化与 execution_focus 生成**

```python
def _execution_focus_payload(state: object, *, owner_role: str | None = None, dimension: str | None = None) -> dict[str, object]:
    gap_tickets = getattr(state, "gap_tickets", []) or []
    watchlist = _watchlist_payload(state)
    snapshot = _memory_payload(state)

    priority_gaps = []
    for ticket in gap_tickets:
        if owner_role is not None and getattr(ticket, "owner_role", None) not in {owner_role, "lead_researcher"}:
            continue
        priority_gaps.append(f"{ticket.target_scope}: {ticket.blocking_reason}")

    if dimension is not None:
        priority_gaps = [gap for gap in priority_gaps if dimension in gap.lower() or "missing dimensions" in gap.lower()]

    return {
        "priority_gaps": priority_gaps[:3],
        "watchlist_entities": [str(item.get("entity_name", "")) for item in watchlist[:3] if item.get("entity_name")],
        "repeated_failures": list(snapshot.get("repeated_failure_patterns", []))[:3],
        "top_competitors": list(snapshot.get("top_competitors", []))[:3],
    }
```

- [ ] **Step 6: 跑 prompt 与 roles 回归**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  tests/test_prompts.py \
  tests/test_roles_llm.py
```

Expected:

```text
all prompt and role tests passed
```

## Task 2: 更深的 Memory/Watchlist 注入

**Files:**
- Modify: `src/jingyantai/agents/roles.py`
- Test: `tests/test_roles_llm.py`
- Test: `tests/test_controller.py`

- [ ] **Step 1: 写失败测试，锁定 analyst 的 execution_focus 会按维度收缩**

```python
def test_analyst_role_execution_focus_prefers_dimension_specific_gap():
    ...
    assert adapter.calls[0][0]["execution_focus"]["priority_gaps"] == [
        "Aider: Missing dimensions: workflow"
    ]
```

- [ ] **Step 2: 写失败测试，锁定 controller 注入的 carry_forward_context 会继续保留 memory 快照而不是被 execution_focus 取代**

```python
def test_controller_preserves_carry_forward_context_while_roles_receive_execution_focus(tmp_path: Path):
    ...
    assert "Legacy One" in captured["carry_forward_context"]
    assert captured["execution_focus"]["watchlist_entities"] == ["Legacy One"]
```

- [ ] **Step 3: 运行失败测试**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  tests/test_roles_llm.py -k "execution_focus" \
  tests/test_controller.py -k "carry_forward_context"
```

Expected:

```text
new execution focus tests fail
```

- [ ] **Step 4: 实现最小的按角色/维度收缩逻辑**

```python
class LeadResearcherRole:
    ...
    "execution_focus": _execution_focus_payload(state, owner_role="lead_researcher"),

class ScoutRole:
    ...
    "execution_focus": _execution_focus_payload(state, owner_role="scout"),

class AnalystRole:
    ...
    "execution_focus": _execution_focus_payload(
        state,
        owner_role="analyst",
        dimension=self.dimension,
    ),
```

- [ ] **Step 5: 跑 roles/controller 回归**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  tests/test_roles_llm.py \
  tests/test_controller.py
```

Expected:

```text
all related tests passed
```

## Task 3: 更准的 Gap Ticket 与更严格的 Stop

**Files:**
- Modify: `src/jingyantai/runtime/judges.py`
- Test: `tests/test_judges.py`

- [ ] **Step 1: 写失败测试，锁定高影响 uncertainty 会阻止 STOP**

```python
def test_stop_judge_blocks_stop_when_high_impact_uncertainties_exceed_stop_bar():
    state = fully_covered_state()
    state.uncertainties.append(
        UncertaintyItem(
            statement="Pricing could change competitor ranking",
            impact="could change competitor ranking",
            resolvability="medium",
            required_evidence="official pricing page",
            owner_role="analyst",
        )
    )

    decision = StopJudge(
        required_dimensions=["workflow"],
        stop_bar=StopBar(min_confirmed_candidates=3, max_high_impact_uncertainties=0),
    ).run(state)

    assert decision.verdict == StopVerdict.CONTINUE
    assert any(ticket.gap_type == "uncertainties" for ticket in decision.gap_tickets)
```

- [ ] **Step 2: 写失败测试，锁定 coverage ratio 不足时即使部分维度齐全也不能 STOP**

```python
def test_stop_judge_uses_min_coverage_ratio_before_stop():
    state = three_confirmed_candidates_only_two_fully_covered()

    decision = StopJudge(
        required_dimensions=["workflow", "pricing"],
        stop_bar=StopBar(min_confirmed_candidates=3, min_coverage_ratio=0.9),
    ).run(state)

    assert decision.verdict == StopVerdict.CONTINUE
    assert any(ticket.gap_type == "coverage" for ticket in decision.gap_tickets)
```

- [ ] **Step 3: 写失败测试，锁定 review/open-question/uncertainty ticket 要尽量带 target scope**

```python
def test_stop_judge_emits_more_specific_gap_ticket_scope_for_open_questions_and_uncertainties():
    state = fully_covered_state()
    state.open_questions.append(
        OpenQuestion(
            question="Pricing page still unclear",
            target_subject="Alpha",
            priority=GapPriority.MEDIUM,
            owner_role="analyst",
            created_by="coverage",
        )
    )
    state.uncertainties.append(
        UncertaintyItem(
            statement="Alpha pricing tiers remain unclear",
            impact="high",
            resolvability="medium",
            required_evidence="pricing page",
            owner_role="analyst",
        )
    )

    decision = StopJudge(required_dimensions=["workflow"]).run(state)

    assert any(ticket.gap_type == "open_questions" and ticket.target_scope == "Alpha" for ticket in decision.gap_tickets)
    assert any(ticket.gap_type == "uncertainties" and ticket.target_scope == "Alpha" for ticket in decision.gap_tickets)
```

- [ ] **Step 4: 运行失败测试**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_judges.py -k "coverage_ratio or high_impact or specific_gap_ticket_scope"
```

Expected:

```text
new stop judge tests fail
```

- [ ] **Step 5: 实现最小 stricter stop 逻辑**

```python
def _high_impact_uncertainty_count(self, state: RunState) -> int:
    return sum(
        1
        for item in state.uncertainties
        if getattr(item, "impact", "") in self.rubric.high_impact_uncertainty_impacts
    )

def _coverage_ratio(self, state: RunState, confirmed: list[Candidate]) -> float:
    if not confirmed:
        return 0.0
    covered_count = 0
    for candidate in confirmed:
        covered = _covered_dimensions_for_candidate(...)
        if len(covered) == len(self.required_dimensions):
            covered_count += 1
    return covered_count / len(confirmed)
```

- [ ] **Step 6: 跑 `tests/test_judges.py` 全量回归**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_judges.py
```

Expected:

```text
all judge tests passed
```

## Task 4: Controller 回归与文档同步

**Files:**
- Test: `tests/test_controller.py`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-04-02-jingyantai-llm-runtime.md`

- [ ] **Step 1: 跑 controller 回归，确认 stricter stop 不会把已有 harness 行为打坏**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_controller.py
```

Expected:

```text
all controller tests passed
```

- [ ] **Step 2: 跑全量回归**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

Expected:

```text
all tests passed
```

- [ ] **Step 3: 同步 README 与增量计划文档**

```markdown
- prompts 已明确围绕 gap_tickets / execution_focus 规划下一轮
- roles 会把 memory/watchlist/gap ticket 摘要收缩成 execution_focus 注入模型层
- StopJudge 现在会检查 coverage ratio 与 high-impact uncertainties，而不只看 confirmed 数量
```

- [ ] **Step 4: Commit**

```bash
git add \
  src/jingyantai/agents/prompts.py \
  src/jingyantai/agents/roles.py \
  src/jingyantai/runtime/judges.py \
  tests/test_prompts.py \
  tests/test_roles_llm.py \
  tests/test_judges.py \
  tests/test_controller.py \
  README.md \
  docs/superpowers/plans/2026-04-02-jingyantai-llm-runtime.md
git commit -m "feat: tighten agent planning and stop quality"
```

## Self-Review

- 覆盖检查：
  - prompt calibration -> Task 1
  - deeper memory/watchlist injection -> Task 1-2
  - better gap tickets -> Task 3
  - stricter stop -> Task 3
  - regression/docs -> Task 4
- 占位符检查：没有 `TODO / TBD / implement later`
- 一致性检查：本阶段不触碰候选源质量、不触碰报告层、不触碰上线层

Plan complete and saved to `docs/superpowers/plans/2026-04-05-jingyantai-phase2-agent-quality.md`。执行时按 `Task 1 -> Task 4` 顺序，不要并行跳步。
