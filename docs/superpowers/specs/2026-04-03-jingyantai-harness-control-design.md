# 竞研台第三阶段设计文档：Harness 控制面与持续研究骨架

## 1. 文档目的

这份设计文档定义 `竞研台` 下一阶段的强化方向：让当前已经成型的 phase-driven harness，进一步具备更强的控制面、停止标准和连续研究能力。

这不是对原始设计稿的替代，而是在现有实现基础上的第三阶段增强设计。它解决的问题不是“如何把第一版跑起来”，而是“如何让它更像真正的 harness，而不是功能已经不少但自治能力仍偏弱的 agent runtime”。

本文的方法论显式参考了 Anthropic 关于长程 agent harness 的两篇工程文章：

- `effective-harnesses-for-long-running-agents`
- `harness-design-long-running-apps`

但会按本项目的硬约束做改写：

- 评估侧 gate 仍以确定性 Python 为主，不把 stop 权交回生成模型
- harness 的核心是研究流程与审计性，而不是把更多智能都塞给一个总模型
- 文章里的 planner / generator / evaluator 思想，会转译成适合竞品研究和本地 artifact 的实现

本文只覆盖 4 个子系统：

- `RuntimePolicy / PhasePolicy` 驱动的运行控制面
- 按错误类型处理的重试与降级策略
- 从规则停机升级为质量收敛停机的 `StopBar`
- 本地 `memory / watchlist` 骨架

## 2. 目标与边界

### 2.1 本阶段目标

- 让 `controller` 从流程编排器升级为显式控制平面
- 让 phase 具备软超时、重试、降级和部分成功语义
- 让 `stop` 从“规则碰巧满足”升级为“硬门槛 + 收敛门槛”
- 让每次 run 不再完全失忆，具备本地可复用研究记忆

### 2.2 非目标

本阶段明确不做以下内容：

- 真正的线程级/协程级强杀超时
- 多 provider 并行调度
- judge 模型化
- 跨机器或多租户 memory
- 定时调度、自动重跑、watch daemon
- 向量数据库或 embedding memory
- 前端 watchlist 管理界面

## 3. 当前问题定义

当前版本已经具备真正的 harness 骨架：

- phase-driven 主循环
- 生成侧 / 评估侧严格分离
- 运行预算、trace、checkpoint、artifact
- 带 citation 的最终报告

但离更成熟的 harness 还有 4 个明显缺口：

1. `controller` 仍然主要是在“按顺序执行各 phase”，控制策略还不够显式。
2. 失败后的策略较弱，当前更多是“记错误并继续”，还不是“理解错误类型后换策略继续”。
3. `StopJudge` 仍偏向规则门槛，不足以表达“结果已经收敛到满意程度”。
4. 每次 run 基本是一次性研究，没有连续研究记忆。

### 3.1 Anthropic 对齐原则

参考 Anthropic 的两篇文章，本阶段新增 6 条显式设计原则：

1. `artifact-first handoff`
   长程任务不能只依赖单次上下文，必须把研究规格、round contract、进度和 evaluator 结果落成结构化 artifact。
2. `planner high-level, executor focused`
   planner 应该给高层目标和完成定义，不应把实现细节过早写死，否则会把错误放大到后续所有 phase。
3. `shared rubric before execution`
   生成侧和评估侧必须共享同一份质量标准，而不是生成后再由 evaluator 临时挑错。
4. `context strategy is explicit`
   对强模型可以偏连续上下文，对容易“context anxiety”的模型要主动做 reset + artifact reload，这必须成为显式策略，而不是隐性副作用。
5. `one gap cluster per contract`
   每一轮 contract 只解决一个研究目标簇，例如“扩展候选”“补 workflow 维度”“解决 pricing 不确定性”，避免一次试图完成整个研究面。
6. `every harness component is load-bearing`
   每增加一个 harness 组件，就意味着在表达“模型单靠自己做不好这件事”。因此这些组件必须做 ablation review，而不是无限叠加。

## 4. 总体设计

本阶段保留现有主结构：

```text
controller -> roles -> tools -> store
```

但新增一层显式控制对象：

```text
HarnessController
  -> RuntimePolicy
    -> ContextStrategy
    -> PhasePolicy
    -> RetryPolicy
    -> DegradeRule
    -> StopBar
    -> QualityRubric
  -> RoundContract
  -> RunMemoryStore
  -> HandoffArtifacts
```

新增的核心对象如下：

- `RuntimePolicy`
  整次 run 的控制配置
- `ContextStrategy`
  定义当前 run 采用连续上下文、周期性 reset，还是混合策略
- `PhasePolicy`
  每个 phase 的软超时、最大尝试次数、是否允许部分成功、降级规则
- `RetryPolicy`
  按错误类型决定 `retry / degrade / skip / fail_phase`
- `DegradeRule`
  定义 scope 收缩、缓存回退、候选降权等动作
- `PhaseOutcome`
  每个 phase 执行后的统一结果对象
- `StopBar`
  硬门槛 + 收敛门槛的停机标准
- `QualityRubric`
  生成侧和评估侧共享的评分维度、硬阈值和拒绝条件
- `RoundContract`
  每轮执行前由 planner 产出的研究合同，定义本轮目标、证据要求和完成定义
- `ConvergenceSnapshot`
  每轮计算出来的质量收敛快照
- `RunMemoryEntry`
  从 run 中抽取出来的长期有效经验
- `WatchlistItem`
  下次仍需关注的实体和未解问题
- `MemorySnapshot`
  提供给下一轮 run 的压缩输入
- `HandoffArtifacts`
  保存 `research spec`、`round contract`、`progress log`、`evaluator log` 等结构化 handoff 文件

## 5. 运行控制面

### 5.1 RuntimePolicy

当前的 `BudgetPolicy` 只描述预算，不足以表达控制面策略。新增 `RuntimePolicy` 后，职责分工如下：

- `BudgetPolicy`
  描述资源上限：
  - `max_rounds`
  - `max_external_fetches`
  - `max_run_duration_minutes`
- `RuntimePolicy`
  描述行为策略：
  - `context_strategy`
  - 各 phase 的 `PhasePolicy`
  - 全局 `RetryPolicy`
  - 全局 `StopBar`
  - 全局 `QualityRubric`
  - 默认降级动作

### 5.2 PhasePolicy

每个 phase 都有独立配置，例如：

- `initialize`
- `expand`
- `deepen`
- `challenge`
- `decide`

每个 `PhasePolicy` 至少包含：

- `soft_timeout_seconds`
- `max_attempts`
- `allow_partial_success`
- `degrade_on`

其中 `soft_timeout_seconds` 的含义是：

- phase 开始时记录 deadline
- 每个 role 执行前检查 deadline
- 每个 role 执行后检查 deadline
- 一旦超时，不再继续本 phase 后续任务
- 进入 `retry / degrade / stop` 判定

本阶段不做强制打断已在执行中的同步阻塞调用，只做软超时。

### 5.3 PhaseOutcome

每个 phase 统一产出一个 `PhaseOutcome`，至少包含：

- `phase`
- `attempt`
- `completed`
- `partial_success`
- `timed_out`
- `error_kinds`
- `degrade_actions`
- `new_candidate_count`
- `new_finding_count`
- `external_fetches`

它的作用是：

- 给 `controller` 决定是否进入下一轮重试或降级
- 给 `StopBar` 和 trace 提供稳定输入
- 让 CLI 和 artifact 更可解释

### 5.4 Controller 改造原则

`HarnessController` 仍是主入口，但执行语义升级为：

```text
run()
  -> load memory snapshot
  -> initialize
  -> for each round:
       expand with phase policy
       deepen with phase policy
       challenge with phase policy
       decide with stop bar
  -> persist state, report, memory, watchlist
```

具体实现上不引入复杂调度器，优先新增内部 helper，例如：

- `_run_phase_with_policy(...)`
- `_handle_phase_failure(...)`
- `_apply_degrade_actions(...)`
- `_build_convergence_snapshot(...)`
- `_build_round_contract(...)`
- `_persist_handoff_artifacts(...)`

### 5.5 Context Strategy 与显式上下文切换

Anthropic 的经验表明，不同模型对长上下文的承受力差异很大；有的模型在大上下文中会表现稳定，有的模型会出现明显的“context anxiety”。

因此本项目不把“是否 reset 上下文”写死为一种默认行为，而是显式引入 `ContextStrategy`：

- `continuous_compaction`
  默认模式，继续沿用当前 `carry_forward_context` + artifact 的方式
- `periodic_reset`
  达到 token、round 或错误触发阈值后，重新构建最小上下文并重新注入 artifact
- `hybrid`
  正常连续运行，出现漂移、schema failure 或 timeout 聚集时切换到 reset

`ContextStrategy` 的核心触发条件应包括：

- 连续 schema failure
- 连续 timeout
- round 数增长后 context 质量下降
- diagnostics 中出现明显漂移

### 5.6 RoundContract 与高层规划纪律

Anthropic 的 harness 设计强调 planner 要给高层目标、规格和完成定义，而不是在最开始就把所有执行细节写死。

对应到 `竞研台`，每轮在进入 `expand / deepen` 前都要生成一份 `RoundContract`，只定义本轮目标簇，而不是试图解决整个研究面。

`RoundContract` 至少包含：

- `target_scope`
- `goal_cluster`
- `must_answer_questions`
- `required_evidence_types`
- `hard_checks`
- `done_definition`
- `fallback_plan`

默认的 `goal_cluster` 应限制为一类目标：

- 扩展候选
- 验证 direct competitor fit
- 补某个维度
- 收敛某个高影响不确定性

为了维持生成侧 / 评估侧分离，本项目不让 planner 自己宣布 contract 合格，而是新增确定性 `ContractJudge` 或 `ContractBar`，检查：

- contract 是否过宽
- hard checks 是否缺失
- done definition 是否可验证
- 是否和当前 stop bar 冲突

## 6. 错误重试与降级策略

### 6.1 错误分类

当前已有部分错误分类，下一阶段统一扩展为 5 类：

- `timeout`
- `schema_validation`
- `provider_request`
- `tool_fetch`
- `bad_candidate`

分类来源：

- LLM runner
- role adapter
- search / extract / github tools
- candidate URL 预检查和证据抓取

### 6.2 RetryDecision

新增统一决策对象 `RetryDecision`，可取值：

- `retry`
- `degrade`
- `skip`
- `fail_phase`

避免每个 role 自己决定是否重试。

### 6.3 DegradeAction

本阶段支持的降级动作保持简单、显式、可测试：

- `reduce_deepen_targets`
- `reduce_search_results`
- `use_cached_results_only`
- `fallback_github_only`
- `mark_candidate_low_confidence`
- `skip_slowest_candidates`

### 6.4 错误到策略的映射

建议默认策略如下：

- `timeout`
  - 先重试一次
  - 仍超时则缩 scope
  - 例如减少 `max_deepen_targets` 或跳过最慢候选
- `schema_validation`
  - 同模型重试一次
  - 第二次失败则标记该 role partial failure
  - 不让整轮直接崩掉
- `provider_request`
  - 如果用户配置 secondary provider/model，则允许 fallback
  - 否则记录 role error 并继续本轮剩余角色
- `tool_fetch`
  - 优先缓存
  - 搜索失败则 GitHub-only
  - 页面抓取失败则 search-hit fallback
- `bad_candidate`
  - 不重试
  - 直接降权或排除

### 6.5 部分成功语义

`expand` 和 `deepen` 默认允许部分成功：

- 某个 scout 失败，不抹掉其他 scout 的结果
- 某个 analyst 失败，不抹掉其他 analyst 对同候选或其他候选的结果

只有 `initialize` 默认不允许部分成功。

## 7. 更强的 StopBar

### 7.1 两层停机标准

停机标准拆成两层：

1. `Hard Gate`
2. `Convergence Gate`

只有两层都通过，系统才认为“结果满意，可以停止”。

### 7.2 Hard Gate

以下条件不过，就绝不能停：

- confirmed competitor 数量达到最低门槛
- 核心 competitor 的 required dimensions 覆盖达标
- 没有高优先级未解决 `gap_ticket`
- 没有高优先级未解决 `review_decision`
- 关键 evidence 质量不过低
- 高影响 uncertainty 不悬空

### 7.3 Convergence Gate

即使 `Hard Gate` 通过，也要判断是否已经收敛：

- 最近一到两轮新增 confirmed competitor 数量很少
- 最近一到两轮新增 findings 的边际收益下降
- 去重后的实体集合趋于稳定
- 高影响 uncertainty 在下降
- comparison matrix 的核心格子不再大幅变化

### 7.4 ConvergenceSnapshot

每轮 `decide` 前生成 `ConvergenceSnapshot`，至少包含：

- `coverage_ratio`
- `evidence_quality_ratio`
- `new_confirmed_this_round`
- `new_findings_this_round`
- `high_impact_uncertainty_count`
- `duplicate_entity_ratio`
- `stagnation_rounds`

`StopJudge` 的行为升级为：

- `hard gate fail` -> `CONTINUE`
- `hard gate pass` 但 `convergence gate fail` -> `CONTINUE`
- 两者都 pass -> `STOP`
- budget stop -> 单独标记为 `forced stop`

### 7.5 Stop 语义要求

最终 trace 和 artifact 必须明确区分：

- `quality_bar_met`
- `forced_stop_due_to_budget`
- `forced_stop_due_to_timeout`

避免把“被迫停”误写成“结果已满意”。

### 7.6 Shared QualityRubric 与 Evaluator 校准

Anthropic 的经验里，一个关键点不是“多一个 evaluator”，而是“生成侧和评估侧共享同一份标准，而且 evaluator 结果要能被校准和复盘”。

本项目在保留确定性 gate 的前提下，增加一份显式 `QualityRubric`，作为以下模块的共享输入：

- `LeadResearcher`
- `Scout`
- `Analyst`
- `EvidenceJudge`
- `CoverageJudge`
- `StopJudge`
- `ContractJudge`

`QualityRubric` 至少包含：

- direct competitor fit 判定标准
- evidence 新鲜度阈值
- evidence 置信度阈值
- 每个维度的最低覆盖要求
- 高影响 uncertainty 的判定条件
- 明确的拒绝条件

同时新增 `evaluator log` artifact，用于保存：

- round contract 被拒绝的原因
- hard gate fail 的具体原因
- convergence gate 未通过的具体指标
- forced stop 的上下文

这些 log 不是只为了调试，而是为了后续 prompt、rubric 和 policy 的校准。后续应维护一小组 `pass / fail / edge case` 标注样本作为 calibration set。

## 8. Memory / Watchlist 骨架

### 8.1 目标

本阶段不做后台调度，只做本地可复用研究记忆。

目标是让下一次 run 不再从零开始，而能消费上一轮压缩后的研究上下文。

### 8.2 数据对象

新增 3 类持久化对象：

- `RunMemoryEntry`
  - confirmed 实体
  - 重复出现的不确定性
  - 稳定可信的来源
  - 重复失败模式
- `WatchlistItem`
  - `entity_name`
  - `canonical_url`
  - `watch_reason`
  - `revisit_trigger`
  - `priority`
  - `last_seen_run_id`
- `MemorySnapshot`
  - top competitors
  - unresolved uncertainties
  - trusted sources
  - repeated failure patterns

### 8.3 持久化方式

继续保持文件型方案，建议同时保存 run 内 handoff artifact 与全局 memory：

```text
runs/
  <run-id>/
    artifacts/
      research-spec.json
      round-contract-000.json
      progress-log.jsonl
      evaluator-log.jsonl
      final-report.json
```

以及当前 runs root 下的全局目录：

```text
runs/
  _global/
    memory.json
    watchlist.json
    latest-snapshot.json
```

这样不破坏现有单次 run 的 artifact 结构，也便于测试。

### 8.4 数据流

每次 run 的数据流如下：

1. run 开始前读取：
   - `latest-snapshot.json`
   - 最近一轮 `research spec`
   - 最近可信的 `trusted sources`
2. 由 `Initializer` 与 `LeadResearcher` 共同产出：
   - `research-spec.json`
   - 当前 round 的 `round-contract.json`
3. 注入给：
   - `Initializer`
   - `LeadResearcher`
   - `Scout`
   - `Analyst`
4. 运行中持续写入：
   - `progress-log.jsonl`
   - `evaluator-log.jsonl`
5. run 结束后从以下信息抽取 memory：
   - `final_report`
   - `traces`
   - `uncertainties`
   - `gap_tickets`
6. 更新：
   - `memory.json`
   - `watchlist.json`
   - `latest-snapshot.json`

### 8.5 Watchlist 的初始用途

第一版 watchlist 只做 3 件事：

- 标记高价值但研究未完成的竞品
- 标记反复失败但值得继续尝试的来源
- 标记影响 stop 的高优先级未解问题

本阶段不自动触发重跑，只为下一轮提供输入。

## 9. 关键接口与文件建议

建议新增或调整这些文件：

- `src/jingyantai/runtime/policies.py`
  - `RuntimePolicy`
  - `ContextStrategy`
  - `PhasePolicy`
  - `RetryPolicy`
  - `DegradeRule`
  - `PhaseOutcome`
  - `StopBar`
  - `QualityRubric`
  - `ConvergenceSnapshot`
- `src/jingyantai/runtime/contracts.py`
  - `RoundContract`
  - `ContractJudge`
  - `ContractBar`
- `src/jingyantai/runtime/memory.py`
  - `RunMemoryEntry`
  - `WatchlistItem`
  - `MemorySnapshot`
  - `FileMemoryStore`
- `src/jingyantai/runtime/controller.py`
  - 接入 phase policy
  - 接入 phase outcome
  - 接入 retry / degrade
  - 接入 memory snapshot 读写
- `src/jingyantai/runtime/judges.py`
  - `StopJudge` 升级为消费 `StopBar` / `ConvergenceSnapshot`
  - judges 消费共享 `QualityRubric`
- `src/jingyantai/cli.py`
  - 暴露运行时 policy 覆盖选项
  - 输出更清晰的 stop 原因

## 10. 错误处理

### 10.1 一般原则

- 不因为单个 scout / analyst 失败而让整轮直接崩溃
- 不因为单个坏 URL 耗尽整轮预算
- 不把被迫停止伪装成质量达标停止
- 所有降级都写入 trace 和 diagnostics
- 不让生成侧自行宣布 contract 完成或质量达标

### 10.2 可解释性要求

每次 `retry / degrade / skip / fail_phase` 都必须进入 trace，至少记录：

- `error_kind`
- `decision`
- `degrade_action`
- `affected_phase`
- `affected_role`

此外，每轮至少要保留以下审计 artifact：

- `round contract`
- `progress log`
- `evaluator log`
- `forced stop reason`

## 11. 测试策略

### 11.1 单元测试

新增测试应覆盖：

- `RuntimePolicy` / `PhasePolicy` 匹配与默认值
- `RetryPolicy` 对不同错误类型的决策
- `StopBar` 的硬门槛与收敛门槛
- `FileMemoryStore` 的读写与快照更新

### 11.2 控制器集成测试

使用 fake roles / fake tools / fake clock 验证：

- soft timeout 会截断 phase 后续执行
- timeout 后触发 scope 缩减
- schema failure 会 partial success
- tool failure 会 fallback 到缓存或 GitHub-only
- forced stop 与 quality stop 被正确区分

### 11.3 真实 smoke

真实 smoke 的目标不是覆盖所有策略，而是验证：

- 正常链路不被新控制层破坏
- 中间 checkpoint 仍然可用
- 最终 report 与 memory / watchlist 同步落盘

### 11.4 Load-Bearing Component Review

Anthropic 的一个重要提醒是：每个 harness 组件本质上都在表达一个假设，即“模型自己做不好这件事，所以需要外部结构”。

因此本项目要求定期做 `ablation review`，至少比较这些组合：

- 有无 `round contract`
- 有无 `QualityRubric`
- 连续上下文 vs `periodic_reset`
- 有无 `memory snapshot`
- 有无 `evaluator log`

如果某个组件去掉后结果没有变差，就说明它可能已经不再 load-bearing，后续应考虑简化，而不是无限叠加 harness 复杂度。

## 12. 实施顺序

建议严格按下面顺序实现：

1. 新增 `runtime/policies.py` 与基础 model
2. 新增 `runtime/contracts.py`，接入 `RoundContract` 与 `ContractJudge`
3. controller 接入 `ContextStrategy`、`PhasePolicy` 与 `PhaseOutcome`
4. 接入 `RetryPolicy` 与 `DegradeAction`
5. 升级 `StopJudge` 为 `StopBar + ConvergenceSnapshot`
6. 新增 `runtime/memory.py`
7. 补 `research spec / progress log / evaluator log` artifact
8. CLI 与 artifact 输出对齐
9. 定向测试与 ablation review
10. fresh 真实 smoke

## 13. 一句话结论

这一阶段的目标不是给现有 harness 再堆更多功能，而是按 Anthropic 长程 harness 的思路，把它从“已经能跑的 agent runtime”推进成“具有显式控制面、共享质量标准、结构化 handoff、质量收敛停机标准和连续研究记忆的真正 harness”。
