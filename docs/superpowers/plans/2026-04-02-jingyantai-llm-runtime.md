# 竞研台 LLM Runtime 与 Harness 增量覆盖计划

> 这不是对 `2026-04-01-jingyantai-harness-mvp.md` 的替代稿，而是补充覆盖文档。原始 MVP 计划继续保留；只有当本文明确写出“覆盖项”时，才以本文为准。

> 2026-04-03 更新说明：本文已从“真实 LLM runtime 接入说明”扩展为“当前实现状态 + 下一阶段 harness 控制面推进顺序”。与 Anthropic 相关文章对齐的第三阶段设计，统一以 `docs/superpowers/specs/2026-04-03-jingyantai-harness-control-design.md` 为设计依据。
>
> 2026-04-05 更新说明：本文补入了第一版的实际交付边界、验收口径和上线前缺口，并把 `phase soft timeout`、更细 budget 统计、watchlist/memory 提取策略等已完成项回写为当前状态。
>
> 2026-04-06 补充更新说明：`phase soft timeout` 已从“仅 phase 前后检查”推进到“phase deadline 注入 tools，晚启动 external fetch 直接跳过”。最新真实 smoke 为 `/tmp/jingyantai-phase4-soft-timeout-20260406/run-20260406025114`；它证明 tool-layer deadline 已生效，但也证明当前仍无法强制打断已经启动的慢 `page_extract`。
>
> 2026-04-06 再补充：shared `QualityRubric` 已补入结构化 `calibration_examples`，并已从 judge / contract 路径推进到生成侧 prompt 与 role payload；生成侧 calibration 不再只依赖第一版 good/bad pattern。
>
> 2026-04-06 再补充二：controller 已开始从 `_global/memory.json` 汇总同 target 的 `historical_memory`，并把 recent runs / recurring competitors / recurring trusted sources / recurring failure patterns 注入生成侧；历史 memory 不再只停留在 `memory_snapshot` 级输入。
>
> 2026-04-06 再补充三：`run_id` 已从秒级时间戳提升为“更细时间粒度 + 随机后缀”；controller 现已支持基于 checkpoint 的 `resume / recovery`，CLI 已补 `resume` 与 `cancel` 入口。当前仍未声称完成 `abort / rerun`。
>
> 2026-04-06 再补充四：针对 `run-20260406025114` 暴露出的 `page_extract` 拖尾，本轮已补两项定向收敛：failed `page_extract` cache，以及 URL precheck 的更短 timeout cap。对应自动化回归已通过，但新的真实 smoke 仍受 DeepSeek DNS/网络失败阻塞，暂不把该项写成真实闭环。
>
> 2026-04-06 再补充五：随后 fresh 真实 smoke 已重新跑通：`/tmp/jingyantai-phase5-page-extract-smoke-20260406-rerun/run-20260406122352492650-527dc6`。本次 run 不再因 `external fetch budget exceeded` 停止，而是以 `round budget exhausted` 正常结束；`external_fetch_count` 从 `47` 降到 `15`，其中 `page_extract` 从 `43` 降到 `10`。但 `phase soft timeout` 仍是协作式控制，`deepen` 阶段仍可被慢请求拖过 soft timeout，因此这里仍不写成完全闭环。
>
> 2026-04-07 再补充六：本轮又补了一层更窄的定向收敛：对“timeout 后已成功 fallback 的主 URL”缓存其 resolved page，避免后续 `build_evidence_bundle()` 在新的 round / role 中再次重试同一个慢主 URL。对应自动化新增测试已通过，fresh 真实 smoke `/tmp/jingyantai-phase5-timeout-cache-smoke-20260407/run-20260406162816603503-3013b4` 也已验证：`external_fetch_count` 从 `15` 进一步降到 `10`，`page_extract` 从 `10` 进一步降到 `7`，且上一轮反复出现的 timeout fallback 已收敛到单次出现。但 `phase soft timeout` 超限依然存在，因此第 5 项仍不写成完全闭环。

## 1. 文档定位

这份文档现在做 4 件事：

- 保留原始 Harness MVP 计划作为基线
- 标出当前实现相对原计划已经发生的偏差
- 记录当前真实落地状态，而不是保留过期的初始判断
- 给出从“真实链路已跑通”继续往 Anthropic 风格 harness 推进的顺序

因此阅读顺序应该是：

1. 先看 `2026-04-01-jingyantai-harness-mvp.md`
2. 再看本文的“覆盖项”和“完成度”
3. 最后看 `2026-04-03-jingyantai-harness-control-design.md`
4. 遇到冲突时，以本文和第三阶段设计稿对应条目覆盖原计划；未冲突部分继续沿用原计划

## 2. 原计划中继续有效的部分

下面这些核心判断没有变，仍然继续有效：

- [x] 项目仍然是一个 phase-driven 的 long-running harness
- [x] 生成侧与评估侧继续严格分离
- [x] `Stop Judge` / `Coverage Judge` / `Challenger` 仍保持确定性 Python gate
- [x] 本地文件型 run store 仍是第一版持久化方案
- [x] `controller -> roles -> tools -> store` 的主结构不变
- [x] deepagents adapter 仍然是生成侧接模型的边界层
- [x] 最终产物仍然是带 citation 的本地 report artifact
- [x] CLI 驱动的本地运行方式仍然是第一版入口

这意味着：原计划关于 harness 主循环、domain model、judge 体系、run artifact、CLI 骨架的方向都没有被推翻。

## 3. 当前实现对原计划的增量覆盖

这里列的是“和原计划有分歧时，应该以当前实现为准”的地方。

### 3.1 搜索 provider 覆盖

原计划写的是 `Tavily`，当前实现已经改为 `Exa`：

- [x] `config.py` 读取 `EXA_API_KEY`
- [x] CLI 默认组装 `ExaSearchClient`
- [x] 上层 `ResearchTools` 仍然只依赖统一搜索接口

覆盖结论：

- 原计划里所有 `Tavily` 相关执行项，现阶段都按 `Exa` 理解
- 这属于 provider 替换，不属于架构重写

### 3.2 生成侧 runtime 覆盖

原计划里有 deepagents adapter，但没有完整展开真实 provider runtime。当前实现已补上：

- [x] 新增 `llm/` 层
- [x] `ProviderConfig`
- [x] `ModelInvocation`
- [x] `build_model_runner()`
- [x] `DeepSeekRunner`

覆盖结论：

- 原计划中的“role 可 later swap 到真实 deepagents-backed 实现”，现在已经不是 future item，而是已完成主线

### 3.3 结构化输出协议覆盖

真实联调后，原计划里“只传 schema 名或口头约束”的强度不够，当前实现已升级为：

- [x] `ModelInvocation` 同时包含 `response_schema_name` 和完整 `response_schema`
- [x] adapter 自动透传 `model_type.model_json_schema()`
- [x] prompt 明确要求模型返回纯 JSON，不再包 `schema/payload`

覆盖结论：

- 今后凡是新增 LLM role，都应沿用“完整 schema + 纯 JSON”协议，而不是退回弱约束写法

### 3.4 默认运行参数覆盖

原始接线阶段偏轻量，当前真实运行默认值已经调整：

- [x] `timeout_seconds` 默认从 `20s` 提高到 `60s`
- [x] CLI 已暴露：
  - `--provider`
  - `--model`
  - `--base-url`
  - `--api-key-env`
  - `--timeout-seconds`
  - `--max-retries`
  - `--runs-dir`

覆盖结论：

- 当前项目已经不是“单一固定 provider 的 demo”
- 但也还没有进入“多 provider 并行实现期”

### 3.5 证据抓取策略覆盖

原计划默认候选 URL 可直接进入 analyst。真实联调后，这一点被现实修正：

- [x] `build_evidence_bundle()` 先抓候选主 URL
- [x] 主 URL 失败时回退到搜索命中的可抓取页面
- [x] 回退原因会写入 diagnostics

覆盖结论：

- 当前 analyst 链路的目标是“尽量继续跑完”，不是“遇到坏 URL 立即整轮失败”

### 3.6 运行观测与 artifact 覆盖

原计划里只强调落盘和 trace，当前实现已经明显增强：

- [x] role/tool/phase 耗时记录
- [x] role error 分类
- [x] 运行中 checkpoint
- [x] CLI 进度输出
- [x] CLI 生成 final report 后回写 `state.json` 和 `final-report.json`
- [x] `round-contract-000.json` handoff artifact
- [x] `progress-log.jsonl` progress artifact
- [x] `stop_reason` 写入 state / progress log / CLI 输出

覆盖结论：

- 当前已经不是“只能跑完后看结果”的黑盒 runtime
- `research spec` 与 `evaluator log` 已经接入当前 controller 路径

### 3.7 控制面第一阶段覆盖

结合 `2026-04-03-jingyantai-harness-control-design.md`，当前已新增第一批控制面原语：

- [x] `RuntimePolicy / PhasePolicy / RetryPolicy`
- [x] `RoundContract / ContractJudge`
- [x] `StopBar`
- [x] file-backed `MemorySnapshot / WatchlistItem / FileMemoryStore`

补充说明：

- `StopBar` 当前是 hard gate + convergence gate 的第一阶段 scaffold
- `latest-snapshot` 加载与 `watchlist/latest-snapshot` 回写已经接入真实 run 路径
- `memory.json` 已接入真实 run 路径，watchlist / memory 提取已不再只是空骨架，而是第一版可用闭环
- `phase soft timeout` 已进一步推进到 tool-layer deadline 传播：controller 会把 phase deadline 注入 `ResearchTools`，由 `search / page_extract / github lookup` 按剩余时间裁剪单次 fetch；deadline 已耗尽时，late fetch 会被直接跳过并记录 diagnostics

### 3.8 Agent 研究质量覆盖

结合 `2026-04-05-jingyantai-phase2-agent-quality.md`，当前 agent 研究循环已经补入第二阶段的核心内核能力：

- [x] `LeadResearcher / Scout / Analyst` prompt 显式消费 `gap_tickets / execution_focus`
- [x] lead prompt 明确要求“选择能关闭命名 gap 的最小下一步”，不再重述整轮 mission
- [x] scout / analyst prompt 已加入 calibration-style good/bad pattern，并要求优先处理当前 bottleneck gap
- [x] shared `QualityRubric` 已补入结构化 `pass / fail / edge_case` calibration sample
- [x] roles 会把 `gap tickets + watchlist + repeated failure patterns + top competitors` 收缩成 `execution_focus` 注入模型层
- [x] roles 现在还会显式接收 `historical_memory`，用于消费同 target 的 recent runs 与 recurring patterns
- [x] analyst 的 `execution_focus` 会按 `dimension` 收缩，避免非瓶颈维度继续膨胀搜索
- [x] `StopJudge` 会按对象范围生成 `open_questions / uncertainties` gap ticket，而不只生成 run 级泛化 ticket
- [x] `StopJudge` 现在会显式检查 `coverage ratio` 与 `high-impact uncertainties`，不再只依赖 confirmed competitor 数量
- [x] controller 已增加 checkpoint-based `resume / recovery` cursor，允许从持久化的下一安全 phase 继续

## 4. 以原计划为基线的完成度

如果按 4 月 1 日原计划来对照，当前状态不是“另起炉灶”，而是：

### 4.1 原主线已经完成的部分

- [x] bootstrap / CLI / README
- [x] domain phases / domain models
- [x] run store
- [x] research tools
- [x] judges
- [x] reporting
- [x] controller 主循环
- [x] deepagents adapter 基础接线

### 4.2 在原计划基础上额外完成的部分

- [x] 真实 LLM runtime 抽象层
- [x] 第一版真实 provider: `DeepSeek`
- [x] `Initializer` / `LeadResearcher` / `Scout` / `Analyst` 真实模型化
- [x] controller 对 `scout/analyst` 失败记录 trace
- [x] 查询 / 页面 / GitHub 级缓存
- [x] fallback 诊断写入 trace
- [x] 同名去重与第二轮实体归一
- [x] 运行中 checkpoint 和 CLI 进度输出
- [x] 真实 API smoke 跑通，且 report artifact 能回写落盘
- [x] `execution_focus` 注入与更严格的 stop gate 回归

### 4.3 原愿景里还没做完、但并不是被删除的部分

- [x] 显式 `RuntimePolicy / PhasePolicy`
- [x] 按错误类型的统一重试 / 降级控制面
- [x] `RoundContract` / `ContractJudge`
- [x] judge / contract 侧 `QualityRubric` 默认配置
- [x] 生成侧 prompt 显式消费 `QualityRubric`
- [x] `evaluator log`
- [x] `Hard Gate + Convergence Gate` 的 stop bar
- [x] 本地 `memory / watchlist` 骨架

补充说明：

- `LeadResearcher / Scout / Analyst` 现在都会显式接收 `quality_rubric`
- role prompt 已明确要求消费 `memory_snapshot / historical_memory / watchlist / quality_rubric`
- prompt 内已加入第一版 calibration-style good/bad pattern，用于约束“单轮只做一个 goal cluster”“证据不足时输出 uncertainty”等行为
- shared `QualityRubric` 现在还会提供结构化 `calibration_examples`，并由 lead / scout / analyst prompt 按 role scope 渲染 `pass / fail / edge_case` 示例
- controller 现在会从 `memory.json` 提取同 target 的 recent runs 与 recurring patterns，形成结构化 `historical_memory` 注入生成侧
- `StopJudge` 已从“confirmed 数量 + 泛化 gap ticket”提升到“coverage ratio / high-impact uncertainty / scoped gap ticket”的更严格停止门槛

### 4.4 第一版当前成立的交付边界

这一节不是新愿景，而是把“现在到底算完成了什么”写死，避免把内核能力和上线能力混在一起。

第一版当前已经成立的，是一个本地可运行、单用户、CLI 驱动的竞品研究 Agent harness：

- [x] 用户可通过 CLI 指定 `provider / model / base_url / api_key_env`
- [x] run 会按 `Initialize -> Expand -> Deepen -> Challenge -> Decide` 多轮推进
- [x] 生成侧与评估侧严格分离
- [x] run 会在达到质量停止条件或 forced stop 条件后结束
- [x] run 会在结束时落盘 `state / final report / research spec / evaluator log / progress log / round contract`
- [x] run 会读取并回写 `_global/latest-snapshot.json / watchlist.json / memory.json`
- [x] phase soft timeout、retry/degrade、external fetch budget breakdown 已接入真实 controller 路径
- [x] CLI 已提供 `run / resume / cancel` 三个本地控制入口

第一版当前还不声称具备下面这些能力：

- [ ] 多用户 / 多租户
- [ ] Web 前端与运营后台
- [ ] 分布式队列、跨进程恢复和 worker 编排
- [ ] 自动调度 / 周期性重跑
- [ ] judge 模型化
- [ ] 多 provider 并行执行

## 5. 当前验证基线

### 5.1 自动化测试

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

结果：

- [x] `169 passed`

### 5.2 真实 smoke

已确认的真实链路：

- [x] `initializer` 真实通过
- [x] `scout` 真实通过
- [x] `analyst` 真实通过
- [x] state / trace / final report 成功落盘
- [x] `research-spec / evaluator-log / latest-snapshot / watchlist / memory` 已在 fresh 真实 micro smoke 中自然产出

当前可复查的示例产物：

- `/tmp/jingyantai-controller-smoke-20260402-reduced60/run-20260402141448/state.json`
- `/tmp/jingyantai-controller-smoke-20260402-reduced60/run-20260402141448/artifacts/final-report.json`
- `/tmp/jingyantai-controller-smoke-20260402-reduced60/run-20260402141448/artifacts/final-report.v2.json`
- `/tmp/jingyantai-harness-control-smoke/run-20260403001918/state.json`
- `/tmp/jingyantai-harness-control-smoke/run-20260403001918/artifacts/final-report.json`
- `/tmp/jingyantai-harness-control-smoke/run-20260403001918/artifacts/round-contract-000.json`
- `/tmp/jingyantai-harness-control-smoke/run-20260403001918/artifacts/progress-log.jsonl`
- `/tmp/jingyantai-micro-smoke-20260403/run-20260403040432/state.json`
- `/tmp/jingyantai-micro-smoke-20260403/run-20260403040432/artifacts/research-spec.json`
- `/tmp/jingyantai-micro-smoke-20260403/run-20260403040432/artifacts/evaluator-log.jsonl`
- `/tmp/jingyantai-micro-smoke-20260403/run-20260403040432/artifacts/final-report.json`
- `/tmp/jingyantai-micro-smoke-20260403/_global/latest-snapshot.json`
- `/tmp/jingyantai-micro-smoke-20260403/_global/watchlist.json`
- `/tmp/jingyantai-micro-smoke-20260403/_global/memory.json`
- `/tmp/jingyantai-phase4-smoke-20260406-rerun/run-20260405162759/state.json`
- `/tmp/jingyantai-phase4-smoke-20260406-rerun/run-20260405162759/artifacts/final-report.json`
- `/tmp/jingyantai-phase4-smoke-20260406-rerun/run-20260405162759/artifacts/research-spec.json`
- `/tmp/jingyantai-phase4-smoke-20260406-rerun/run-20260405162759/artifacts/evaluator-log.jsonl`
- `/tmp/jingyantai-phase4-smoke-20260406-rerun/run-20260405162759/artifacts/progress-log.jsonl`
- `/tmp/jingyantai-phase4-soft-timeout-20260406/run-20260406025114/state.json`
- `/tmp/jingyantai-phase4-soft-timeout-20260406/run-20260406025114/artifacts/final-report.json`
- `/tmp/jingyantai-phase4-soft-timeout-20260406/run-20260406025114/artifacts/research-spec.json`
- `/tmp/jingyantai-phase4-soft-timeout-20260406/run-20260406025114/artifacts/evaluator-log.jsonl`
- `/tmp/jingyantai-phase4-soft-timeout-20260406/run-20260406025114/artifacts/progress-log.jsonl`

补充说明：

- `final-report.v2.json` 是用最新 reporting 逻辑对真实 `state.json` 重新生成的报告
- 该复算结果已证明第二轮实体归一生效，`Codex` 与 `OpenAI Codex` 的重复项被压掉
- `run-20260403001918` 是引入 control-plane artifacts 后的真实 smoke，已确认：
  - CLI 按 phase 输出 progress
  - controller 落盘 `round-contract-000.json` 与 `progress-log.jsonl`
  - run 最终因 `external fetch budget exceeded: 52/30` 强制停止，`stop_reason` 已写入 progress log
  - 该样本生成于 `research-spec` 接线前，因此还没有 `research-spec.json`
  - 该样本也生成于 `evaluator-log` 接线前，因此还没有 `evaluator-log.jsonl`
- `run-20260403040432` 是 prompt/rubric/memory 接线后的 fresh 真实 micro smoke，已确认：
  - `research-spec.json / evaluator-log.jsonl / final-report.json / progress-log.jsonl / round-contract-000.json` 都会自然产出
  - `_global/latest-snapshot.json / watchlist.json / memory.json` 都会在 run 结束后自然回写
  - `expand` 阶段真实输出已显式带上 `confidence threshold 0.6` 与 `freshness threshold 0.2`，证明生成侧 prompt 正在消费 shared `QualityRubric`
- `run-20260405162759` 是 2026-04-06 的 fresh phase-4 smoke，已确认：
  - `python -m jingyantai.cli run ...` 入口可直接启动真实链路
  - `state.json / final-report.json / research-spec.json / evaluator-log.jsonl / progress-log.jsonl / round-contract-000..003.json` 都会自然产出
  - run 最终因 `external fetch budget exceeded: 35/30 (github_lookup=2, page_extract=30, search=3)` 显式停止，`stop_reason` 已写入 CLI / state / progress log / evaluator log
  - report 已不再因为 `brief.required_dimensions` 与真实 findings 脱节而输出整表 `0/N`
  - citation 已收敛到更高可信的 canonical / official URL 集合
- `run-20260406025114` 是 2026-04-06 的 fresh soft-timeout smoke，已确认：
  - `ResearchTools` 已收到 phase deadline，真实 trace 中出现 `phase runtime deadline exceeded before external fetch`
  - `expand` 与 `deepen` 阶段都已经能跳过 late fetch，而不是在 deadline 后继续发起新的 `github/search/page_extract`
  - run 最终仍因 `external fetch budget exceeded: 47/30 (github_lookup=1, page_extract=43, search=3)` 停止，说明当前主要瓶颈已集中到 `page_extract`
  - `expand` 真实 trace 已出现 `soft timeout exceeded for phase expand: 59.844/30.000s`
  - `deepen` 真实 trace 已出现 `soft timeout exceeded for phase deepen: 86.967/60.000s`
- 基于这份 trace，2026-04-06 又补了第一轮定向收敛：
  - 同一个已知失败 URL 现在会进入 failed `page_extract` cache，避免在后续 bundle / round / role 中重复外部抓取
  - `search_competitor_candidates()` 的 URL precheck 现在会使用更短 timeout cap，避免单次慢 precheck 把 `expand` 拖长
  - fresh 自动化验证已通过：`tests/test_research_tools.py` 新增覆盖失败 URL cache 与 precheck timeout cap；`tests/test_controller.py`、`tests/test_cli.py` 与全量 `pytest` 当前 fresh 结果分别为 `25 passed`、`9 passed`、`172 passed`
  - 当时首次真实 smoke 重跑仍未成功，因为那次尝试运行 `python -m jingyantai.cli run ...` 时，provider 初始化阶段即因 `api.deepseek.com` DNS/网络失败中止
- `/tmp/jingyantai-phase5-page-extract-smoke-20260406-rerun/run-20260406122352492650-527dc6` 是随后补齐的 fresh 真实 smoke，已确认：
  - run 最终 `stop_reason` 为 `round budget exhausted: next round 5 exceeds max_rounds=4`，而不是 `external fetch budget exceeded`
  - `external_fetch_count` 从旧样本 `47` 降到 `15`
  - `external_fetch_breakdown` 从旧样本 `search=3, page_extract=43, github_lookup=1` 收敛到 `search=2, page_extract=10, github_lookup=3`
  - `000-expand` 的 `page_extract` 耗时从旧样本 `43811ms` 降到 `17205ms`
  - `001-deepen` 的 `external_fetches` 从旧样本 `14` 降到 `4`
  - run 现已自然产出 `state.json / final-report.json / research-spec.json / evaluator-log.jsonl / progress-log.jsonl / round-contract-000..004.json`
  - 最新真实链路仍保留 residual gap：`deepen` 中同一超时主 URL 仍会多次出现 `fallback to search hit https://code.claude.com/docs/en/overview`，且多个 `deepen` phase 仍超过 soft timeout
- `/tmp/jingyantai-phase5-timeout-cache-smoke-20260407/run-20260406162816603503-3013b4` 是 2026-04-07 的 fresh timeout-fallback-cache smoke，已确认：
  - run 继续以 `round budget exhausted: next round 5 exceeds max_rounds=4` 正常停止，没有退化回 `external fetch budget exceeded`
  - `external_fetch_count` 从上一 fresh 样本 `15` 进一步降到 `10`
  - `external_fetch_breakdown` 从上一 fresh 样本 `search=2, page_extract=10, github_lookup=3` 进一步收敛到 `search=2, page_extract=7, github_lookup=1`
  - 上一 fresh 样本中跨 round 反复出现的 timeout fallback，本次只在 `round 2` 出现 1 次：`primary extract failed: The read operation timed out; fallback to github search hit https://opencode.ai/docs/github`
  - `round 0/1 deepen` 的 `external_fetches` 都保持为 `0`，说明“同一个 timeout 主 URL 的跨轮重复抓取”已经被压住
  - 当前剩余的主要真实链路问题已不再是 page-level 重复抓取，而是 `phase soft timeout` 仍可能被慢角色执行与重试/降级路径拖过，例如 `120.131/60.000s`
- 截至 2026-04-06，后续新增的 `phase soft timeout`、更细 fetch breakdown、watchlist/memory richer extraction、`execution_focus` 注入、`StopJudge` stricter stop gate、报告层标准化交付、`python -m` CLI 入口、round budget/forced stop 语义 已通过自动化回归验证；当前剩余的主要真实链路问题是：`phase soft timeout` 虽已推进到 tool-layer deadline 注入，但仍是协作式控制，已经启动的慢请求仍可能把 phase 明显拖过 soft timeout

### 5.3 第一版验收口径

下面这些条件同时成立时，可以认为“第一版 Agent 内核已经成立”：

- [x] 可以从 CLI 启动一次完整 run，并在 `STOP` 或 `forced stop` 结束
- [x] 生成侧与评估侧的职责边界没有被破坏
- [x] run 至少会稳定产出 `state.json`、`artifacts/final-report.json`、`artifacts/research-spec.json`、`artifacts/evaluator-log.jsonl`、`artifacts/progress-log.jsonl`、`artifacts/round-contract-000.json`
- [x] 历史 `memory_snapshot / watchlist` 会在 run 开始时注入，并在 run 结束后回写
- [x] controller 已具备 soft timeout、retry/degrade、fetch budget、forced stop、gap-driven rerun 这些最小 harness 控制能力
- [x] 当前自动化测试基线保持为全绿

## 6. 当前 backlog 的真实完成度

这里不再使用 4 月 2 日时的“全部待做”口径，而是按当前真实状态更新。

### 6.1 Phase A: 候选质量层

目标：减少错误链接、低质量候选、错误 canonical URL 进入 deepen。

- [x] URL 规范化
- [x] 候选主链接可达性预检查
- [x] GitHub repo / 官网优先级策略
- [x] scout 输出后的更强 filtering / ranking
- [x] 把“回退到搜索命中页”的原因写入 trace
- [x] 同名与近似实体的第一轮、第二轮归一
- [x] GitHub richer signals 参与候选排序
- [x] evidence bundle 按维度选择更合适的证据入口页

当前判断：

- 这一层已经从“基础规范化”推进到“前置质量过滤 + richer ranking”
- 针对真实 trace 暴露出的 `page_extract` 拖尾，已补 failed extract cache 与 URL precheck timeout cap，先减少重复失败抓取和慢 precheck 拖尾
- fresh 真实 smoke 先证明这两项收敛已把 `external fetch budget exceeded` 从主停止原因里移开；随后新增的 timeout-fallback resolution cache 又把“超时型 primary extract 跨轮重复出现”从反复发生压到单次发生
- 当前还没做的是更强的跨来源实体合并、候选质量打分标准化，以及更细的 canonical URL 策略

### 6.2 Phase B: 运行可观测性层

目标：让真实 run 的慢点和失败点可诊断。

- [x] 记录每个 role 的开始/结束耗时
- [x] 记录 DeepSeek / Exa / GitHub / 页面抓取耗时
- [x] 记录 fallback 原因
- [x] 区分 provider timeout / extract failure / schema failure / bad URL
- [x] 运行中 checkpoint
- [x] CLI 进度输出
- [x] `research spec` artifact
- [x] `round contract` artifact
- [x] `progress log` artifact
- [x] `evaluator log` artifact

当前判断：

- 这一层大部分已完成
- 下一步不是再加零散日志，而是进入结构化 handoff artifact

### 6.3 Phase C: 长程 Harness 控制层

目标：把“能跑 smoke”推进到“能更稳定地跑完整 harness”。

- [x] `ContextStrategy`
- [x] `RuntimePolicy / PhasePolicy`
- [x] phase 级 soft timeout
- [x] 更细的外部请求 budget 统计
- [x] 区分模型重试与搜索重试策略
- [x] 统一 `RetryDecision / DegradeAction`
- [x] `RoundContract` / `ContractJudge`
- [x] `Hard Gate + Convergence Gate`
- [x] 更清晰地区分 `quality stop` 与 `forced stop`

这一层正是“能一直运行到满意结果再停止”的主要落点。  
生成侧和评估侧严格分离的思想不是后补项，而是已经成立的底线；真正还没做实的是：如何让控制面、收敛判断和上下文策略支撑长程运行。

### 6.4 Phase D: 报告质量层

目标：让最终产物更接近可展示的真实竞品研究结果。

- [x] 同名候选去重
- [x] 近似名 / 品牌前缀 / 产品线后缀归一
- [ ] canonical URL 统一继续增强
- [x] citation 去重
- [x] citation 质量检查
- [x] comparison matrix 关键维度补强
- [x] 置信度标准化
- [x] uncertainty 分层标准化

当前判断：

- 报告质量已经明显脱离玩具态
- comparison matrix 已显式带 `coverage / confidence_band`
- citations 已从“全收集”提升到“质量筛选 + 排序”
- uncertainty 已按优先级排序并做标准格式输出
- judge / contract 层已经进入 shared rubric 阶段
- 生成侧 prompt 显式消费已经落地
- shared `QualityRubric` 已补入 `pass / fail / edge_case` 标注样本，生成侧 calibration 已不再只停留在第一版 prompt pattern 阶段

### 6.5 Phase E: 连续研究骨架

目标：让 run 之间不再完全失忆。

- [x] `RunMemoryEntry`
- [x] `WatchlistItem`
- [x] `MemorySnapshot`
- [x] 全局 `memory.json`
- [x] 全局 `watchlist.json / latest-snapshot.json` file store 骨架
- [x] run 开始时注入历史 snapshot
- [x] run 结束后更新 `latest-snapshot.json / watchlist.json / memory.json`

当前判断：

- 这一层已经从“只有骨架”推进到“snapshot/watchlist/memory 真接线”
- [x] 第一版 watchlist / memory richer extraction 已接线，包括从 coverage review 与 gap ticket 中提取未解问题
- [x] 历史 memory 更深地注入生成侧已接线，当前会把同 target 的 recent runs / recurring competitors / recurring trusted sources / recurring failure patterns 汇总成 `historical_memory`

## 7. 上线前必须补的非功能缺口

下面这些项不影响“第一版内核成立”，但会影响你后面是否敢把它当真实线上项目推进：

- [x] `run_id` 唯一性增强，避免秒级时间戳在高频触发时碰撞
- [x] checkpoint-based resume / recovery 机制，允许长程 run 从持久化的下一安全 phase 恢复
- [ ] `abort / rerun` 的显式控制入口；`cancel` 已接线，但当前仍未补独立 rerun/abort 命令
- [ ] 把 `phase soft timeout` 从当前“tool-layer deadline + late fetch skip”推进到“更强的实际打断/截断能力”
- [ ] provider 限流、成本预算和失败重试的更清晰运营口径
- [ ] 更清晰的用户入口定义，包括 provider/model 选择的注册与展示方式
- [x] fresh 真实 smoke 回归，把 2026-04-05 新增控制面行为带入真实链路验证

## 8. 下一阶段的正确推进顺序

从现在开始，不建议继续以“再补几个功能点”的方式推进。考虑到控制面第一阶段已经落地，下一步顺序应改为：

1. 以 `2026-04-03-jingyantai-harness-control-design.md` 作为设计基线
2. [x] `QualityRubric` 已推进到更强的 calibration sample，不再只是第一版 good/bad prompt pattern
3. [x] 历史 memory 已更深地注入生成侧，而不止是 snapshot/watchlist 级输入
4. [x] `run_id` 唯一性、checkpoint-based `resume / recovery`、以及 `cancel` 入口已接线
5. 基于 `run-20260406025114` 的真实 trace，继续收敛 `page_extract` 拖尾与 fetch budget overshoot，而不是再泛泛加功能点
   当前状态：已完成两轮定向收敛，并已拿到 fresh 真实 smoke 证据；`external fetch budget overshoot` 已从 `47/30` 收敛到 `10` 次总抓取，超时型 `primary extract` 跨轮重复也已从反复出现收敛到单次出现。当前还未闭环的是 `phase soft timeout` 超限，因此这一步仍保持进行中，但 page_extract 侧的主问题已经基本压住

## 9. 现在不建议优先做的事

这些不是否定，而是排期靠后：

- [ ] 多 provider 同时实现
- [ ] judge 模型化
- [ ] 自动调度 / 定时重跑
- [ ] 跨机器 memory
- [ ] 多租户 / 账号系统
- [ ] 大规模前端包装

## 10. 一句话结论

正确理解当前状态的方式不是“旧方案作废、换了一份新方案”，而是：

- 旧方案仍然是骨架
- 真实 LLM/runtime 接入已经把骨架的一部分做实
- 候选质量、观测性、报告质量已经有实质进展
- 下一阶段真正要补的是 Anthropic 风格 harness 的控制面、合同化执行、共享 rubric 和连续研究记忆
