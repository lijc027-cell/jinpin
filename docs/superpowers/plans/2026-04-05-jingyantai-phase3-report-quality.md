# 竞研台 Phase 3 报告交付质量 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让最终报告更接近真实可展示的竞品研究交付物，而不是只有基础去重和原始摘要。

**Architecture:** 保持 `FinalReport` 顶层接口基本稳定，不重写 CLI 或 store。增强点集中在 `reporting.py`：补 citation 质量筛选与排序、comparison matrix 的覆盖/置信度标准化，以及 uncertainty 的分层与排序。这样可以在不打散现有运行链路的前提下，提高最终 artifact 的可读性和可信度。

**Tech Stack:** Python, pytest, Pydantic, 当前 `Synthesizer / CitationAgent / FinalReport`

---

## 范围与非范围

本计划只覆盖 `Phase 3（D）报告交付质量`：

- citation 质量筛选与更好的排序
- comparison matrix 的覆盖表达补强
- 置信度分级标准化
- uncertainty 文本的分层、排序与去重

明确不在本计划内：

- controller 主循环
- judge 逻辑
- memory / watchlist / stop gate
- Web 前端展示

## 文件结构

- Modify: `src/jingyantai/runtime/reporting.py`
  - 增加 citation 质量筛选、矩阵字段补强、uncertainty 标准化 helper
- Test: `tests/test_reporting.py`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-04-02-jingyantai-llm-runtime.md`

## Task 1: Citation 质量筛选与排序

**Files:**
- Modify: `src/jingyantai/runtime/reporting.py`
- Test: `tests/test_reporting.py`

- [ ] **Step 1: 写失败测试，锁定 article-like citation 在存在官网/仓库时不会进入最终引用**

```python
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
            Evidence(..., subject_id="gemini", source_url="https://taskade.com/blog/claude-code-alternatives/", source_type="web"),
            Evidence(..., subject_id="gemini", source_url="https://github.com/google/gemini-cli", source_type="github"),
            Evidence(..., subject_id="gemini", source_url="https://ai.google.dev/gemini-api/docs/cli", source_type="official"),
        ]
    )

    final = CitationAgent().run(state, Synthesizer().run(state))

    assert final.citations["Gemini CLI"] == [
        "https://ai.google.dev/gemini-api/docs/cli",
        "https://github.com/google/gemini-cli",
    ]
```

- [ ] **Step 2: 运行失败测试**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_reporting.py -k "prefers_official_and_repo_urls"
```

Expected:

```text
new citation quality test fails
```

- [ ] **Step 3: 实现最小 citation 质量筛选**

```python
def _citation_quality(url: str) -> tuple[int, int, str]:
    ...

def _select_citation_urls(candidate: object, group: list, state: RunState) -> list[str]:
    urls = [...]
    if any(not _is_article_like(url) for url in urls):
        urls = [url for url in urls if not _is_article_like(url)]
    return sorted(urls, key=_citation_quality)
```

- [ ] **Step 4: 跑 reporting 回归**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_reporting.py -k "citation"
```

Expected:

```text
all citation tests passed
```

## Task 2: Comparison Matrix 覆盖表达与置信度标准化

**Files:**
- Modify: `src/jingyantai/runtime/reporting.py`
- Test: `tests/test_reporting.py`

- [ ] **Step 1: 写失败测试，锁定 matrix 会输出 coverage 与 confidence_band**

```python
def test_synthesizer_adds_coverage_and_confidence_band_to_matrix():
    state = _state()
    ...
    draft = Synthesizer().run(state)
    row = draft.comparison_matrix[0]

    assert row["coverage"] == "2/3"
    assert row["confidence_band"] == "high"
```

- [ ] **Step 2: 写失败测试，锁定缺失维度不再是空串而是明确缺口文本**

```python
def test_synthesizer_marks_missing_dimensions_explicitly():
    state = _state()
    ...
    row = Synthesizer().run(state).comparison_matrix[0]

    assert row["pricing or access"] == "Missing direct evidence"
```

- [ ] **Step 3: 运行失败测试**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_reporting.py -k "coverage_and_confidence_band or missing_dimensions_explicitly"
```

Expected:

```text
new matrix tests fail
```

- [ ] **Step 4: 实现最小 matrix 增强**

```python
def _confidence_band(score: float) -> str:
    if score >= 0.85:
        return "high"
    if score >= 0.65:
        return "medium"
    return "low"
```

- [ ] **Step 5: 跑 reporting 回归**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_reporting.py -k "synthesizer"
```

Expected:

```text
all synthesizer tests passed
```

## Task 3: Uncertainty 分层、排序与去重

**Files:**
- Modify: `src/jingyantai/runtime/reporting.py`
- Test: `tests/test_reporting.py`

- [ ] **Step 1: 写失败测试，锁定 uncertainty 会按 impact/resolvability 排序并标准化格式**

```python
def test_synthesizer_sorts_and_formats_uncertainties_by_priority():
    state = _state()
    state.uncertainties.extend([...])

    items = Synthesizer().run(state).key_uncertainties

    assert items[0].startswith("[high][medium]")
    assert "required evidence: official pricing page" in items[0]
```

- [ ] **Step 2: 写失败测试，锁定重复 uncertainty 不会重复进入最终报告**

```python
def test_synthesizer_dedupes_equivalent_uncertainties():
    state = _state()
    state.uncertainties.extend([... same statement variants ...])

    items = Synthesizer().run(state).key_uncertainties

    assert len(items) == 1
```

- [ ] **Step 3: 运行失败测试**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_reporting.py -k "formats_uncertainties or dedupes_equivalent_uncertainties"
```

Expected:

```text
new uncertainty tests fail
```

- [ ] **Step 4: 实现最小 uncertainty 标准化**

```python
def _uncertainty_sort_key(item: object) -> tuple[int, int, str]:
    ...

def _format_uncertainty(item: object) -> str:
    return f"[{impact}][{resolvability}] {statement} | required evidence: {required_evidence}"
```

- [ ] **Step 5: 跑 reporting 全量回归**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_reporting.py
```

Expected:

```text
all reporting tests passed
```

## Task 4: 文档同步与全量回归

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-04-02-jingyantai-llm-runtime.md`

- [ ] **Step 1: 跑全量测试**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

Expected:

```text
all tests passed
```

- [ ] **Step 2: 同步文档状态**

```markdown
- citation agent 会做 citation 质量筛选与排序
- comparison matrix 现在带 coverage / confidence_band
- key_uncertainties 现在按优先级排序并做标准化格式
```
