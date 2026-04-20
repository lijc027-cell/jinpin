# 竞研台设计文档

## 1. 一句话定义

`竞研台` 是一个面向小团队的长程竞品研究 Harness。它不是“搜资料然后总结”的普通 AI 应用，而是一个持续运行的 research runtime，使用严格分离的生成侧与评估侧，在质量门槛满足前持续迭代研究，直到 `Stop Judge` 放行或触发预算/断路器。

## 2. 背景与问题

围绕 `Claude Code` 这类 coding agent / terminal agent / developer agent 产品做竞品研究，天然不是简单的后端工作流问题，原因包括：

- 竞品空间开放，不能预先枚举固定名单。
- 候选产品存在同名、别名、公司与产品边界混淆问题。
- 研究必须在多个维度收集证据，而不是从单一来源得出结论。
- 中间结论经常需要被反证和修正。
- 一次 run 往往需要多轮搜索、筛选、补查、收敛。

因此，这个项目的核心不是“竞品搜索”，而是一个能长程运行、受约束地循环推进、保留研究状态并在质量达标后才停止的 Harness。

## 3. 产品目标

### 3.1 第一版目标

给定一个目标产品，例如 `Claude Code`，系统应能够自主完成一次完整竞品研究 run，并产出以下结果：

- `RunTrace`：记录本次研究的阶段推进、任务派发、补查、停机裁定和关键决策。
- `Evidence Pack`：结构化证据包，而不是零散网页摘要。
- `Competitor Decisions`：明确哪些被确认、哪些被排除，以及原因。
- `Final Report`：带引用的最终竞品研究报告。

### 3.2 第一版必须证明的能力

- `research autonomy`
  系统能够自主制定和调整研究计划，而不是执行硬编码步骤。
- `candidate funneling`
  系统能够把候选从发现逐步推进到确认或排除。
- `generator/evaluator separation`
  生成与评估严格分离，不能由同一角色既产出内容又宣布“足够好了”。
- `evidence-grounded reasoning`
  关键结论必须由结构化证据支撑。
- `long-running harness behavior`
  系统能持续运行多轮，直到满足显式停止条件。

## 4. 非目标

以下内容明确不进入第一版实现范围：

- 跨 run 长期记忆
- 自动定时重跑
- watchlist / alerts
- 多租户
- 复杂团队审批流
- 泛行业产品研究
- 面向所有赛道的通用知识平台

这些能力可以写入后续路线，但不应污染第一版边界。

## 5. 设计原则

### 5.1 Harness-first

系统主体是运行时，而不是某个“大 agent”。运行时负责状态、预算、轮次、阶段推进、断路器和停机裁定。

### 5.2 Long-running until satisfactory

系统必须在未满足质量门槛时持续补查。`满意` 不是模糊主观感受，而是由 `Stop Judge` 基于结构化标准判定。

### 5.3 Generator / Evaluator 严格分离

生成侧只负责发现、研究、整理；评估侧只负责审查、质疑、发缺口、裁定是否可停。两侧必须在协议层分离，而不是只在提示词里“建议分工”。

### 5.4 Evidence-first

关键结论不直接写入报告，必须先落成 `Evidence` 和 `Finding`，再进入交付阶段。

### 5.5 Context engineering

上下文必须分层管理，并通过独立的 `Context Compactor` 控制跨轮传递，避免运行几轮后被历史噪音淹没。

### 5.6 Phase-driven runtime

系统必须按显式阶段推进，而不是让多个 agent 自由漫游。

## 6. 目标对象与研究范围

第一版目标对象限定为：

- `Claude Code` 及其直接竞品
- 类似的 coding agent / terminal agent / developer agent 产品

第一版研究重点维度：

- `positioning`
- `workflow`
- `core capabilities`
- `pricing or access`
- `community / ecosystem signal`

竞品分类原则：

- `direct competitor`
  提供高度重叠的工作流与目标用户价值。
- `indirect competitor`
  能替代部分使用场景，但形态或目标用户存在显著差异。
- `non-competitor`
  相关但不构成真正购买或使用替代。

## 7. 运行时总览

### 7.1 运行时定位

`竞研台` 的核心是 `Harness Controller`。它负责：

- 阶段推进
- 预算控制
- 状态持久化
- 上下文压缩
- 任务派发
- 断路器
- 停机入口

系统架构分三层：

- `运行时层`
  `Harness Controller`、`Run State Store`、`Context Compactor`
- `生成侧`
  `Initializer`、`Lead Researcher`、`Scout Agents`、`Analyst Agents`、`Synthesizer`
- `评估侧`
  `Evidence Judge`、`Coverage Judge`、`Challenger`、`Stop Judge`、`Citation Agent`

### 7.2 为什么 Citation Agent 归到评估/交付边界

引用整理不应与研究阶段混在一起。研究结束后，引用需要单独回链、查缺和完整性检查，因此单列 `Citation Agent`。

## 8. 第一版角色设计

### 8.1 运行时层

#### `Harness Controller`

职责：

- 管理主循环和阶段转移
- 维护预算与断路器
- 将评估结果转换为下一轮可执行任务
- 决定回退到哪个阶段，而不是整轮重跑

禁止事项：

- 不直接研究竞品
- 不直接生成最终结论

#### `Run State Store`

职责：

- 保存 `ResearchBrief`
- 保存候选池、证据、findings、gap tickets
- 保存每轮 `RunTrace`
- 支持多轮恢复

#### `Context Compactor`

职责：

- 每轮输出压缩后的跨轮上下文
- 维护热/温/冷上下文边界
- 避免无关历史污染活跃研究

### 8.2 生成侧

#### `Initializer`

职责：

- 把用户输入转成 `ResearchBrief`
- 生成 `RunCharter`
- 定义竞品判定标准
- 设定必需研究维度和预算策略
- 生成初始假设板

#### `Lead Researcher`

职责：

- 制定本轮 `RoundPlan`
- 根据 `GapTickets` 设计补查策略
- 分发任务给 scout 或 analyst
- 汇总各角色产出，形成下一轮行动提议

禁止事项：

- 不能自行宣布研究完成
- 不能跳过评估侧

#### `Scout Agents`

第一版建议 3 个：

- 官网/产品定位侦察员
- GitHub/技术生态侦察员
- 社区热度侦察员

职责：

- 扩展候选池
- 收集高信号初始证据
- 生成初步 `OpenQuestion`

#### `Analyst Agents`

第一版建议 3 个：

- 定位与用户场景分析员
- 功能与工作流分析员
- 定价与商业化分析员

职责：

- 对 Top-K 候选做定向深挖
- 输出结构化 findings 和不确定性

#### `Synthesizer`

职责：

- 将已确认 findings 组织成报告草稿
- 不参与停机裁定
- 不负责补证

### 8.3 评估侧

#### `Evidence Judge`

职责：

- 检查证据是否足够直接、足够新、足够可靠
- 标记低质量或冲突证据

#### `Coverage Judge`

职责：

- 检查每个候选是否覆盖关键维度
- 产出维度缺口

#### `Challenger`

职责：

- 质疑候选是否真的是直接竞品
- 寻找反证和冲突证据
- 推荐排除或降级

#### `Stop Judge`

职责：

- 根据 run state 和评估结果判断 `STOP` 或 `CONTINUE`
- 若继续，必须生成结构化 `GapTickets`

禁止事项：

- 不生成新的研究结论
- 不自己补查资料

#### `Citation Agent`

职责：

- 在最终交付前补齐引用映射
- 检查结论与证据回链完整性

## 9. 主循环与阶段定义

第一版运行时主循环固定为：

```text
INITIALIZE -> EXPAND -> CONVERGE -> DEEPEN -> CHALLENGE -> DECIDE -> STOP | LOOP_BACK
```

### 9.1 `INITIALIZE`

输入：

- 用户目标
- 产品类型
- 用户强调的关注点

输出：

- `ResearchBrief`
- `RunCharter`
- `CompetitorDefinition`
- `InitialHypotheses`
- `BudgetPolicy`

进入下一阶段条件：

- 竞品定义完整
- 必需维度完整
- 预算策略已设定

### 9.2 `EXPAND`

由 scout agents 并行扩展候选池和研究假设。

输出：

- `CandidateDelta`
- `EvidenceDelta`
- `OpenQuestionDelta`

进入下一阶段条件：

- 获得可归一的一批候选
- 候选来源不全部来自单一来源

### 9.3 `CONVERGE`

职责：

- 去重
- 实体归一
- 候选打分
- 推进漏斗状态

输出：

- `normalized candidates`
- `prioritized candidates`

进入下一阶段条件：

- Top-K 可确定
- 有明确的深挖对象

### 9.4 `DEEPEN`

由 analyst agents 对 Top-K 做定向深挖。

输出：

- `FindingDelta`
- `EvidenceDelta`
- `UncertaintyDelta`

进入下一阶段条件：

- Top-K 至少覆盖最基础研究维度
- 已形成初版 findings

### 9.5 `CHALLENGE`

由评估侧对当前研究进行审查。

输出：

- `EvidenceAssessment`
- `CoverageAssessment`
- `ChallengeAssessment`
- `GapTickets`

进入下一阶段条件：

- 三类核心审查都已完成

### 9.6 `DECIDE`

由 `Stop Judge` 读取全部审查结果和预算状态，做出：

- `STOP`
- `CONTINUE`

若 `CONTINUE`，必须给出：

- 缺口类型
- 目标范围
- owner role
- 验收规则

### 9.7 定向回退

系统回环时不能默认回到最开始，而要根据缺口类型定向回退：

- 候选不足：回到 `EXPAND`
- 候选排序不稳：回到 `CONVERGE`
- 某维度证据不足：回到 `DEEPEN`
- 关键结论遭到反证：回到 `DEEPEN`，必要时退回 `CONVERGE`

## 10. 协议层分离

### 10.1 生成协议

生成侧允许输出的对象：

- `CandidateDelta`
- `EvidenceDelta`
- `FindingDelta`
- `OpenQuestionDelta`
- `UncertaintyDelta`
- `ProposedNextActions`

### 10.2 评估协议

评估侧允许输出的对象：

- `EvidenceAssessment`
- `CoverageAssessment`
- `ChallengeAssessment`
- `GapTickets`
- `StopVerdict`

协议层分离的目的：

- 生成侧不能自判完成
- 评估侧不能偷偷补研究
- 运行时能用结构化对象推动循环，而不是拼接自然语言

## 11. 数据对象

### 11.1 `ResearchBrief`

字段：

- `target`
- `product_type`
- `competitor_definition`
- `required_dimensions`
- `budget`
- `stop_policy`

### 11.2 `RunCharter`

字段：

- `mission`
- `scope`
- `non_goals`
- `success_criteria`
- `research_agenda`

### 11.3 `Hypothesis`

字段：

- `statement`
- `status`：`untested / supported / weakened / rejected`
- `related_candidates`
- `supporting_evidence_ids`
- `conflicting_evidence_ids`

### 11.4 `Candidate`

字段：

- `candidate_id`
- `name`
- `aliases`
- `canonical_url`
- `company`
- `status`
- `relevance_score`
- `why_candidate`
- `why_not_candidate`

状态机：

```text
discovered -> normalized -> plausible -> prioritized -> confirmed / rejected
```

### 11.5 `Evidence`

字段：

- `evidence_id`
- `subject_id`
- `claim`
- `source_url`
- `source_type`
- `snippet`
- `captured_at`
- `freshness_score`
- `confidence`
- `supports_or_conflicts`

### 11.6 `Finding`

字段：

- `finding_id`
- `subject_id`
- `dimension`
- `summary`
- `evidence_ids`
- `confidence`
- `conflict_flags`

### 11.7 `OpenQuestion`

字段：

- `question`
- `target_subject`
- `priority`
- `owner_role`
- `created_by`

### 11.8 `UncertaintyItem`

字段：

- `statement`
- `impact`
- `resolvability`
- `required_evidence`
- `owner_role`

### 11.9 `GapTicket`

字段：

- `gap_type`
- `target_scope`
- `blocking_reason`
- `owner_role`
- `acceptance_rule`
- `deadline_round`
- `priority`
- `retry_count`

### 11.10 `ReviewDecision`

字段：

- `judge_type`
- `target_scope`
- `verdict`
- `reasons`
- `required_actions`

### 11.11 `RunTrace`

字段：

- `round_index`
- `phase`
- `planner_output`
- `dispatched_tasks`
- `new_candidates`
- `new_findings`
- `review_decisions`
- `stop_or_continue`

### 11.12 `FinalReport`

字段：

- `target_summary`
- `confirmed_competitors`
- `rejected_candidates`
- `comparison_matrix`
- `key_uncertainties`
- `citations`

## 12. 评分与质量门

### 12.1 候选相关性评分

第一版针对 `Claude Code`，优先考虑：

- `workflow_overlap`
- `user_overlap`
- `form_factor_overlap`
- `capability_overlap`
- `market_signal_overlap`

此分数用于资源分配，而不是直接替代最终判定。

### 12.2 证据质量评分

考虑：

- `source_authority`
- `freshness`
- `directness`
- `corroboration`
- `conflict_penalty`

### 12.3 覆盖度评分

每个确认竞品至少要覆盖：

- `positioning`
- `workflow`
- `core capabilities`
- `pricing or access`
- `community / ecosystem signal`

### 12.4 确认竞品的最小质量门槛

`confirmed competitor` 至少满足：

- 至少 2 条独立证据
- 至少 1 条官方来源
- 至少覆盖 3 个关键维度
- `Challenger` 没有未解决的致命异议

## 13. 停止机制

系统满足以下条件时才能停：

- 核心竞品数量达到最低要求
- 每个核心竞品满足最小证据门槛
- 高优先级 `OpenQuestion` 降到阈值以下
- 关键维度覆盖达标
- `Challenger` 没有未解决的致命异议

如果不满足，`Stop Judge` 必须输出可执行 `GapTickets`，而不能只说“还不够”。

## 14. 上下文工程

### 14.1 上下文分层

- `hot context`
  当前轮计划、Top-K 候选、高优先级 gap tickets、致命不确定性
- `warm context`
  上一轮摘要、已确认 findings 摘要、已排除候选、当前假设状态
- `cold artifacts`
  原始搜索结果、长网页摘录、完整证据库、历史 trace

### 14.2 压缩规则

每轮结束由 `Context Compactor` 统一输出：

- `Round Summary`
- `CarryForwardContext`
- `ResolvedItems`
- `PendingItems`

agent 不得自行把整轮长历史原样带入下一轮。

## 15. 预算与断路器

### 15.1 第一版预算

- `max_rounds`
- `max_candidates_in_active_pool`
- `max_deepen_targets`
- `max_external_fetches`
- `max_run_duration`

### 15.2 第一版断路器

- 连续两轮没有新增高价值候选
- 连续两轮证据质量没有明显提升
- `GapTickets` 重复出现且无法关闭
- 预算逼近上限但 stop readiness 没明显改进

断路器不是错误，而是 runtime 的保护机制。

## 16. 工具面设计

第一版对 agent 暴露的应是“研究动作”，而不是底层抓取原语。

### 16.1 生成侧工具

- `search_competitor_candidates`
- `resolve_product_identity`
- `collect_positioning_evidence`
- `collect_workflow_evidence`
- `collect_pricing_access_evidence`
- `collect_github_ecosystem_signals`
- `collect_market_heat_signals`
- `build_evidence_bundle`

### 16.2 评估侧工具

- `assess_evidence_quality`
- `assess_dimension_coverage`
- `challenge_competitor_fit`
- `issue_gap_tickets`
- `judge_stop_readiness`

## 17. 离线评测方向

第一版只要求定义而不追求复杂平台：

- `competitor_recall@k`
- `false_positive_rate`
- `evidence_coverage`
- `stop_judge_precision`

运行内评估与离线工程评估必须分离。

## 18. 第一版实现范围

第一版必须实现：

- `Harness Controller`
- `Run State Store`
- `Initializer`
- `Lead Researcher`
- 3 个 `Scout Agents`
- 3 个 `Analyst Agents`
- `Evidence Judge`
- `Coverage Judge`
- `Challenger`
- `Stop Judge`
- `Context Compactor`
- `Synthesizer`
- `Citation Agent`
- 结构化对象与候选状态机
- `Hypothesis Board`
- `Uncertainty Register`
- `GapTickets`
- 预算和断路器

第一版允许简化：

- `Hypothesis Board` 先做轻量版本
- `Uncertainty Register` 先只记录高优先级项
- `热度侦察员` 先聚焦 GitHub、Hacker News、官方博客

## 19. 后续扩展

以下内容进入后续路线，而不进入第一版：

- 跨 run 长期记忆
- 自动定时重跑
- watchlist
- alerts
- 多项目研究面板
- 团队审批流
- 多租户

## 20. 面试与上线叙事

对面试和后续产品化，这个项目的正确叙事是：

`竞研台` 不是一个竞品搜索 demo，而是一个面向小团队的长程竞品研究 Harness。它通过候选漏斗、严格分离的生成侧与评估侧、结构化证据对象、上下文压缩、反证审查和停机裁判机制，持续运行到研究质量满足阈值为止。
