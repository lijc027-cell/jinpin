# 竞研台 Phase 1 候选与证据底座 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提升候选竞品与证据入口的质量，让后续 Agent 轮次建立在更干净的输入之上。

**Architecture:** 这一阶段只动工具层与最薄的角色接线层，不碰 stop 逻辑、不碰报告格式、不碰上线能力。`ResearchTools` 负责候选筛选、URL 预检查、证据入口选择；`GitHubSignals` 负责补强仓库活跃度与发布信号；现有 `ScoutRole` / `AnalystRole` 继续透传 richer payload，不增加新的 orchestration。

**Tech Stack:** Python, pytest, httpx, Pydantic, 现有 `ResearchTools` / `GitHubSignals` / `ScoutRole` / `AnalystRole`

---

## 范围与非范围

本计划只覆盖 `A + C` 的第一阶段内容：

- 候选主链接可达性预检查
- `scout` 前的候选过滤与排序增强
- 更强的 `canonical_url` 与候选实体统一
- GitHub 仓库信号补强
- 证据页入口选择增强

明确不在本计划内的内容：

- prompt calibration
- stop bar / convergence 逻辑
- 最终报告格式增强
- Web/API/队列/恢复运行

## 文件结构

本阶段只修改现有文件，避免继续把项目拆散：

- Modify: `src/jingyantai/tools/github_signals.py`
  - 为 GitHub 仓库增加 release / latest commit / issue count / forks 等 richer signals
- Modify: `src/jingyantai/tools/research_tools.py`
  - 增加候选 URL 预检查
  - 增加候选过滤与排序增强
  - 增加按维度选择证据页的 resolver
- Modify: `src/jingyantai/agents/roles.py`
  - 只在需要时补轻量参数透传，不增加新职责
- Test: `tests/test_research_tools.py`
  - 覆盖 GitHub richer signals、候选筛选、证据页选择
- Test: `tests/test_roles_llm.py`
  - 覆盖 richer raw candidate / richer bundle 仍会稳定透传

## Task 1: GitHub 信号补强

**Files:**
- Modify: `src/jingyantai/tools/github_signals.py`
- Test: `tests/test_research_tools.py`

- [ ] **Step 1: 写失败测试，定义 richer GitHub signal 的最小返回面**

```python
def test_github_signals_enriches_repo_results_with_release_and_commit_metadata():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/repositories":
            return httpx.Response(
                status_code=200,
                json={
                    "items": [
                        {
                            "full_name": "Aider-AI/aider",
                            "stargazers_count": 24000,
                            "updated_at": "2026-03-29T10:00:00Z",
                            "forks_count": 2100,
                            "open_issues_count": 320,
                            "default_branch": "main",
                            "description": "AI pair programmer in your terminal.",
                        }
                    ]
                },
                request=request,
            )
        if request.url.path == "/repos/Aider-AI/aider/releases/latest":
            return httpx.Response(
                status_code=200,
                json={"tag_name": "v0.81.0", "published_at": "2026-03-28T00:00:00Z"},
                request=request,
            )
        if request.url.path == "/repos/Aider-AI/aider/commits":
            return httpx.Response(
                status_code=200,
                json=[{"commit": {"committer": {"date": "2026-03-29T09:00:00Z"}}}],
                request=request,
            )
        raise AssertionError(request.url.path)

    signals = GitHubSignals(http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    result = signals.lookup("aider")

    assert result == [
        {
            "repo": "Aider-AI/aider",
            "stars": 24000,
            "updated_at": "2026-03-29T10:00:00Z",
            "forks": 2100,
            "open_issues": 320,
            "default_branch": "main",
            "description": "AI pair programmer in your terminal.",
            "latest_release_tag": "v0.81.0",
            "latest_release_published_at": "2026-03-28T00:00:00Z",
            "latest_commit_at": "2026-03-29T09:00:00Z",
        }
    ]
```

- [ ] **Step 2: 写失败测试，定义 enrichment 失败时的 fail-open 行为**

```python
def test_github_signals_keeps_base_repo_result_when_release_lookup_fails():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/repositories":
            return httpx.Response(
                status_code=200,
                json={
                    "items": [
                        {
                            "full_name": "acme/agent-kit",
                            "stargazers_count": 900,
                            "updated_at": "2026-03-30T00:00:00Z",
                        }
                    ]
                },
                request=request,
            )
        if request.url.path == "/repos/acme/agent-kit/releases/latest":
            return httpx.Response(status_code=404, json={"message": "Not Found"}, request=request)
        if request.url.path == "/repos/acme/agent-kit/commits":
            return httpx.Response(status_code=200, json=[], request=request)
        raise AssertionError(request.url.path)

    signals = GitHubSignals(http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    result = signals.lookup("agent-kit")

    assert result[0]["repo"] == "acme/agent-kit"
    assert result[0]["stars"] == 900
    assert result[0]["latest_release_tag"] == ""
    assert result[0]["latest_commit_at"] == ""
```

- [ ] **Step 3: 运行失败测试，确认红灯来自缺失字段而不是测试本身**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  tests/test_research_tools.py::test_github_signals_enriches_repo_results_with_release_and_commit_metadata \
  tests/test_research_tools.py::test_github_signals_keeps_base_repo_result_when_release_lookup_fails
```

Expected:

```text
2 failed
```

- [ ] **Step 4: 在 `github_signals.py` 实现最小 enrichment**

```python
class GitHubSignals:
    def _get(self, path: str, *, params: dict[str, object] | None = None) -> httpx.Response:
        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        url = f"https://api.github.com{path}"
        if self.http_client is None:
            return httpx.get(url, params=params, headers=headers, timeout=self.timeout_seconds, trust_env=False)
        return self.http_client.get(url, params=params, headers=headers, timeout=self.timeout_seconds)

    def _latest_release(self, repo: str) -> tuple[str, str]:
        response = self._get(f"/repos/{repo}/releases/latest")
        if response.status_code == 404:
            return "", ""
        response.raise_for_status()
        payload = response.json()
        return str(payload.get("tag_name", "")), str(payload.get("published_at", ""))

    def _latest_commit_at(self, repo: str, default_branch: str) -> str:
        response = self._get(f"/repos/{repo}/commits", params={"sha": default_branch, "per_page": 1})
        response.raise_for_status()
        payload = response.json()
        if not payload:
            return ""
        return str(payload[0].get("commit", {}).get("committer", {}).get("date", ""))

    def lookup(self, query: str) -> list[dict[str, str | int]]:
        search_response = self._get(
            "/search/repositories",
            params={"q": query, "sort": "stars", "order": "desc", "per_page": self.per_page},
        )
        search_response.raise_for_status()
        repos = []
        for item in search_response.json().get("items", []):
            repo = str(item.get("full_name", ""))
            default_branch = str(item.get("default_branch", ""))
            latest_release_tag = ""
            latest_release_published_at = ""
            latest_commit_at = ""
            if repo:
                try:
                    latest_release_tag, latest_release_published_at = self._latest_release(repo)
                    if default_branch:
                        latest_commit_at = self._latest_commit_at(repo, default_branch)
                except httpx.HTTPError:
                    pass
            repos.append(
                {
                    "repo": repo,
                    "stars": int(item.get("stargazers_count", 0)),
                    "updated_at": str(item.get("updated_at", "")),
                    "forks": int(item.get("forks_count", 0)),
                    "open_issues": int(item.get("open_issues_count", 0)),
                    "default_branch": default_branch,
                    "description": str(item.get("description", "")),
                    "latest_release_tag": latest_release_tag,
                    "latest_release_published_at": latest_release_published_at,
                    "latest_commit_at": latest_commit_at,
                }
            )
        return repos
```

- [ ] **Step 5: 运行 GitHub signals 相关测试并确认通过**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_research_tools.py -k "github_signals"
```

Expected:

```text
selected github signal tests passed
```

## Task 2: 候选 URL 预检查与排序增强

**Files:**
- Modify: `src/jingyantai/tools/research_tools.py`
- Test: `tests/test_research_tools.py`

- [ ] **Step 1: 写失败测试，定义 root site 可达优先于 docs/blog 子页**

```python
def test_search_competitor_candidates_prefers_reachable_root_site_over_unreachable_docs_hit():
    class SearchClient:
        def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
            return [
                SearchHit(title="Foo Docs", url="https://docs.foo.dev", snippet="Docs."),
                SearchHit(title="Foo", url="https://foo.dev", snippet="Official site."),
            ]

    class PageExtractor:
        def extract(self, url: str) -> PageData:
            if url == "https://docs.foo.dev":
                raise RuntimeError("docs blocked")
            return PageData(url=url, title="Foo", text="Official site", excerpt="Official site")

    tools = ResearchTools(
        search_client=SearchClient(),
        page_extractor=PageExtractor(),
        github_signals=FakeGitHubSignalsClient(),
    )

    candidates = tools.search_competitor_candidates(
        target="Claude Code",
        hypothesis="agent",
        source_mix=["web"],
        max_results=5,
    )

    assert candidates[0]["canonical_url"] == "https://foo.dev"
    assert candidates[0]["candidate_quality"]["url_precheck"] == "ok"
    assert all(item["canonical_url"] != "https://docs.foo.dev" for item in candidates)
```

- [ ] **Step 2: 写失败测试，定义 GitHub 活跃仓库排序要考虑新信号而不是只看 stars**

```python
def test_search_competitor_candidates_uses_richer_github_activity_signals_in_rank():
    class GithubSignalsClient:
        def lookup(self, query: str) -> list[dict[str, str | int]]:
            return [
                {
                    "repo": "acme/legacy-agent",
                    "stars": 5000,
                    "updated_at": "2025-01-01T00:00:00Z",
                    "latest_commit_at": "2025-01-01T00:00:00Z",
                    "latest_release_tag": "",
                },
                {
                    "repo": "acme/active-agent",
                    "stars": 3200,
                    "updated_at": "2026-04-01T00:00:00Z",
                    "latest_commit_at": "2026-04-01T00:00:00Z",
                    "latest_release_tag": "v1.4.0",
                },
            ]

    tools = ResearchTools(
        search_client=EmptySearchClient(),
        page_extractor=FakePageExtractor(),
        github_signals=GithubSignalsClient(),
    )

    candidates = tools.search_competitor_candidates(
        target="Claude Code",
        hypothesis="coding agent",
        source_mix=["github"],
        max_results=5,
    )

    assert candidates[0]["canonical_url"] == "https://github.com/acme/active-agent"
```

- [ ] **Step 3: 运行失败测试，确认是现有排序策略不满足要求**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  tests/test_research_tools.py::test_search_competitor_candidates_prefers_reachable_root_site_over_unreachable_docs_hit \
  tests/test_research_tools.py::test_search_competitor_candidates_uses_richer_github_activity_signals_in_rank
```

Expected:

```text
2 failed
```

- [ ] **Step 4: 在 `research_tools.py` 实现最小预检查与排序逻辑**

```python
def _safe_precheck_url(self, url: str) -> tuple[str, str]:
    try:
        page = self._extract_page(url)
        return "ok", page.url
    except Exception as exc:
        self._note(f"url precheck failed for {url}: {exc}")
        return "failed", url

def _github_activity_score(self, candidate: dict[str, str | int]) -> tuple:
    latest_release = str(candidate.get("latest_release_tag", ""))
    latest_commit = str(candidate.get("latest_commit_at", ""))
    updated_at = str(candidate.get("updated_at", ""))
    return (
        0 if latest_release else 1,
        0 if latest_commit or updated_at else 1,
        -int(candidate.get("stars", 0)),
    )

def _candidate_rank_key(self, candidate: dict[str, str | int]) -> tuple:
    url = str(candidate["canonical_url"])
    parsed = urlparse(url)
    depth = len([segment for segment in parsed.path.split("/") if segment])
    source = str(candidate["source"])
    if source == "web":
        precheck_penalty = 0 if candidate.get("candidate_quality", {}).get("url_precheck") == "ok" else 1
        return (0, precheck_penalty, 1 if self._is_docs_like(url) else 0, depth, str(candidate["name"]).lower())
    return (1, *self._github_activity_score(candidate), depth, str(candidate["name"]).lower())

def search_competitor_candidates(
    self,
    target: str,
    hypothesis: str,
    source_mix: list[str],
    max_results: int = 5,
) -> list[dict[str, str]]:
    self._reset_metrics()
    candidates: list[dict[str, str | int]] = []
    source_set = set(source_mix)
    if "web" in source_set:
        hits = self._search_or_empty(
            query=f"{target} competitor {hypothesis}",
            max_results=max_results,
            note_prefix="web search",
        )
        for hit in hits:
            normalized_url = self._normalize_url(hit.url)
            precheck_status, resolved_url = self._safe_precheck_url(normalized_url)
            if precheck_status != "ok" and self._is_docs_like(normalized_url):
                continue
            candidates.append(
                {
                    "candidate_id": "",
                    "name": hit.title or urlparse(normalized_url).netloc or "candidate",
                    "canonical_url": normalized_url,
                    "why_candidate": hit.snippet,
                    "source": "web",
                    "domain": urlparse(normalized_url).netloc,
                    "candidate_quality": {
                        "url_precheck": precheck_status,
                        "resolved_url": resolved_url,
                    },
                }
            )
    return [dict(candidate) for candidate in sorted(candidates, key=self._candidate_rank_key)]
```

- [ ] **Step 5: 运行 `search_competitor_candidates` 相关测试并确认通过**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_research_tools.py -k "search_competitor_candidates"
```

Expected:

```text
selected candidate ranking tests passed
```

## Task 3: 证据页入口选择增强

**Files:**
- Modify: `src/jingyantai/tools/research_tools.py`
- Test: `tests/test_research_tools.py`
- Test: `tests/test_roles_llm.py`

- [ ] **Step 1: 写失败测试，定义 workflow 和 pricing 优先找更合适的证据页**

```python
def test_build_evidence_bundle_prefers_dimension_specific_pages_when_search_hits_exist():
    class SearchClient:
        def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
            if query == "Aider":
                return [
                    SearchHit(title="Aider", url="https://aider.chat", snippet="Official site."),
                    SearchHit(title="Aider Docs", url="https://aider.chat/docs", snippet="Docs."),
                    SearchHit(title="Aider Pricing", url="https://aider.chat/pricing", snippet="Pricing."),
                ]
            return []

    class Extractor:
        def extract(self, url: str) -> PageData:
            return PageData(url=url, title=url, text=f"text for {url}", excerpt=f"excerpt for {url}")

    tools = ResearchTools(
        search_client=SearchClient(),
        page_extractor=Extractor(),
        github_signals=FakeGitHubSignalsClient(),
    )

    bundle = tools.build_evidence_bundle(subject="Aider", url="https://aider.chat")

    assert bundle["positioning"]["source_url"] == "https://aider.chat"
    assert bundle["workflow"]["source_url"] == "https://aider.chat/docs"
    assert bundle["pricing_or_access"]["source_url"] == "https://aider.chat/pricing"
    assert bundle["diagnostics"]["dimension_sources"] == {
        "positioning": "primary_url",
        "workflow": "workflow_search_hit",
        "pricing_or_access": "pricing_search_hit",
    }
```

- [ ] **Step 2: 写失败测试，保护 `AnalystRole` 对 richer bundle 的透传**

```python
def test_analyst_role_passes_dimension_specific_bundle_through_to_adapter():
    tools = FakeToolset()
    tools.build_evidence_bundle = lambda subject, url: {
        "positioning": {"summary": "Official site", "source_url": "https://aider.chat"},
        "workflow": {"summary": "Docs", "source_url": "https://aider.chat/docs"},
        "pricing_or_access": {"summary": "Pricing", "source_url": "https://aider.chat/pricing"},
        "github": [{"repo": "Aider-AI/aider", "latest_release_tag": "v0.81.0"}],
        "heat": {},
        "diagnostics": {"dimension_sources": {"workflow": "workflow_search_hit"}},
    }
    adapter = StaticAdapter(AnalystOutput.model_validate({"evidence": [], "findings": [], "uncertainties": []}))
    role = AnalystRole(
        tools=tools,
        adapter=adapter,
        dimension="workflow",
        role_name="analyst_workflow",
    )
    state = RunState(run_id="run-1", target="Claude Code", current_phase=Phase.DEEPEN, budget=_budget())
    candidate = Candidate(
        candidate_id="cand-aider",
        name="Aider",
        canonical_url="https://aider.chat",
        status=CandidateStatus.CONFIRMED,
        relevance_score=0.9,
        why_candidate="direct",
    )
    role.run(state, candidate)
    assert adapter.calls[0][0]["bundle"]["workflow"]["source_url"] == "https://aider.chat/docs"
    assert adapter.calls[0][0]["bundle"]["pricing_or_access"]["source_url"] == "https://aider.chat/pricing"
    assert adapter.calls[0][0]["bundle"]["diagnostics"]["dimension_sources"]["workflow"] == "workflow_search_hit"
```

- [ ] **Step 3: 运行失败测试，确认当前 bundle resolver 只会复用主页面**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  tests/test_research_tools.py::test_build_evidence_bundle_prefers_dimension_specific_pages_when_search_hits_exist \
  tests/test_roles_llm.py::test_analyst_role_passes_dimension_specific_bundle_through_to_adapter
```

Expected:

```text
2 failed
```

- [ ] **Step 4: 在 `research_tools.py` 实现最小的维度页 resolver**

```python
def _pick_dimension_page(self, subject: str, dimension: str, primary_url: str, search_hits: list[SearchHit]) -> tuple[PageData, str]:
    keyword_map = {
        "positioning": ["overview", "product", "home"],
        "workflow": ["docs", "documentation", "guide", "quickstart"],
        "pricing or access": ["pricing", "plans", "billing"],
    }
    normalized_primary = self._normalize_url(primary_url)
    ranked_urls = [normalized_primary]
    for hit in search_hits:
        normalized = self._normalize_url(hit.url)
        if normalized not in ranked_urls:
            ranked_urls.append(normalized)
    for url in ranked_urls:
        if dimension == "positioning" and url == normalized_primary:
            return self._extract_page(url), "primary_url"
        if any(token in url.lower() for token in keyword_map[dimension]):
            return self._extract_page(url), f"{dimension.replace(' ', '_').replace('/', '_')}_search_hit"
    return self._extract_page(normalized_primary), "primary_url"

def build_evidence_bundle(self, subject: str, url: str) -> dict[str, object]:
    diagnostics = {
        "requested_url": url,
        "resolved_url": resolved_url,
        "resolved_via": resolved_via,
        "fallback_reason": fallback_reason,
    }
    search_hits = self._search_or_empty(query=subject, max_results=3, note_prefix="subject search")
    positioning_page, positioning_source = self._pick_dimension_page(subject, "positioning", resolved_url, search_hits)
    workflow_page, workflow_source = self._pick_dimension_page(subject, "workflow", resolved_url, search_hits)
    pricing_page, pricing_source = self._pick_dimension_page(subject, "pricing or access", resolved_url, search_hits)
    return {
        "positioning": self._evidence_from_page(subject, positioning_page, "positioning"),
        "workflow": self._evidence_from_page(subject, workflow_page, "workflow"),
        "pricing_or_access": self._evidence_from_page(subject, pricing_page, "pricing or access"),
        "github": github_hits,
        "heat": heat,
        "diagnostics": {
            "requested_url": diagnostics["requested_url"],
            "resolved_url": diagnostics["resolved_url"],
            "resolved_via": diagnostics["resolved_via"],
            "fallback_reason": diagnostics["fallback_reason"],
            "dimension_sources": {
                "positioning": positioning_source,
                "workflow": workflow_source,
                "pricing_or_access": pricing_source,
            },
        },
    }
```

- [ ] **Step 5: 运行证据 bundle 与角色透传测试并确认通过**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  tests/test_research_tools.py -k "build_evidence_bundle" \
  tests/test_roles_llm.py -k "analyst_role"
```

Expected:

```text
selected evidence bundle and analyst role tests passed
```

## Task 4: Phase 1 回归验证

**Files:**
- Modify: `src/jingyantai/tools/github_signals.py`
- Modify: `src/jingyantai/tools/research_tools.py`
- Modify: `src/jingyantai/agents/roles.py`（如 Task 3 需要）
- Test: `tests/test_research_tools.py`
- Test: `tests/test_roles_llm.py`
- Test: `tests/test_controller.py`

- [ ] **Step 1: 跑工具层与角色层定向回归**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  tests/test_research_tools.py \
  tests/test_roles_llm.py
```

Expected:

```text
all passed
```

- [ ] **Step 2: 跑 controller 回归，确认 richer candidates/bundles 不会破坏 harness 主循环**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_controller.py
```

Expected:

```text
all passed
```

- [ ] **Step 3: 跑全量回归**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

Expected:

```text
131+ passed
```

- [ ] **Step 4: 记录 Phase 1 行为变化到 README 与运行计划文档**

```markdown
- 候选现在会做 URL 预检查，不再把明显不可达 docs/blog 页面直接送入 deepen
- GitHub 仓库信号已补强到 release / commit / issue / fork 级别
- evidence bundle 会按维度优先选择更合适的证据页，而不只复用主页面
```

- [ ] **Step 5: Commit**

```bash
git add \
  src/jingyantai/tools/github_signals.py \
  src/jingyantai/tools/research_tools.py \
  src/jingyantai/agents/roles.py \
  tests/test_research_tools.py \
  tests/test_roles_llm.py \
  tests/test_controller.py \
  README.md \
  docs/superpowers/plans/2026-04-02-jingyantai-llm-runtime.md
git commit -m "feat: harden source selection and evidence inputs"
```

## Self-Review

- 覆盖检查：
  - GitHub richer signals -> Task 1
  - 候选 URL 预检查与排序 -> Task 2
  - 证据页入口选择 -> Task 3
  - 回归与文档同步 -> Task 4
- 占位符检查：本计划没有 `TODO / TBD / implement later` 之类空项
- 一致性检查：
  - 计划只动工具层与轻量角色透传
  - 不把 stop logic、reporting、前端、上线能力混入本阶段

Plan complete and saved to `docs/superpowers/plans/2026-04-05-jingyantai-phase1-source-quality.md`。下一步建议直接按这个计划执行 `Task 1 -> Task 4`，不要并行跳步。
