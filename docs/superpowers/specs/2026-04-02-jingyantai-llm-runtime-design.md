# 竞研台第二阶段设计文档：真实 LLM Runtime 增量覆盖稿

## 1. 文档目的

这份文档不是为了替代最初的 Harness 设计稿，而是给它增加一层“当前真实落地状态”的覆盖说明。

未发生冲突的设计判断，继续沿用原始方案；只有当本文明确指出“当前实现已经改成这样”时，才以本文为准。

它回答 4 个问题：

- 这一阶段实际做成了什么
- 实现过程中相对原方案发生了哪些偏移
- 真实联调暴露了哪些问题，以及已经如何修正
- 从当前状态继续往后做，系统的正确演进方向是什么

因此更准确的理解应该是：

- 原始 Harness 设计稿定义骨架
- 本文解释真实 provider 接入后，骨架哪些部分已经落地
- 本文补充说明哪些地方因为真实联调被修正

## 2. 当前阶段已经实现的目标

截至当前版本，以下目标已经实现：

- 生成侧 4 个核心角色已经走真实 LLM：
  - `Initializer`
  - `LeadResearcher`
  - `Scout`
  - `Analyst`
- 评估侧仍保持确定性 Python gate，不做模型化
- LLM runtime 已抽象为 provider-agnostic 接口
- 第一版真实 provider 已落地 `DeepSeek`
- 搜索侧已接入真实搜索 API
- CLI 已支持运行时选择：
  - `provider`
  - `model`
  - `base_url`
  - `api_key_env`
  - `timeout_seconds`
  - `max_retries`
- role 异常会记录到 trace，而不是直接把整轮 run 打死

## 3. 相对原设计的关键修正

### 3.1 搜索 provider 从 Tavily 改为 Exa

最初方案默认使用 Tavily，但实际注册流程不可用，因此搜索后端改为 `ExaSearchClient`。

这次替换不是架构方向变化，而是搜索 provider 的实现替换。上层仍然只依赖统一的 `SearchClient` 协议。

影响如下：

- 业务层 `ResearchTools` 不需要改接口
- CLI 与 Settings 改为读取 `EXA_API_KEY`
- 搜索返回值仍然规整为：
  - `title`
  - `url`
  - `snippet`

### 3.2 模型调用不能只传 schema 名字，必须传完整 schema

原始方案只给模型传 `response_schema_name`。真实联调表明这不够：

- DeepSeek 会生成“看起来像结构化输出，但字段完全不匹配”的 JSON
- 初始化阶段曾真实返回：
  - 顶层是 `schema/payload`
  - 内层字段是模型自己发明的 `researchBrief/runCharter`

因此当前实现已改为：

- `ModelInvocation` 包含：
  - `response_schema_name`
  - `response_schema`
- adapter 在调用前用 `model_type.model_json_schema()` 生成完整 schema
- runner 把 schema 与明确指令一起发给模型：
  - 只返回 JSON
  - 不要再包一层 `schema/payload`

这是当前真实 LLM runtime 能稳定工作的核心修正。

### 3.3 默认模型超时从 20s 提高到 60s

原始默认值 `20s` 适合轻量测试，不适合真实结构化生成。

真实联调表明：

- `initializer` 较快
- `scout` 与 `analyst` 在真实链路里明显更慢
- `15s` 已经稳定超时
- `60s` 能支撑当前 smoke 级真实链路

因此当前默认配置已经调整为：

- `timeout_seconds = 60.0`

这不是性能优化，而是现实运行条件下的最小稳定默认值。

### 3.4 analyst 前增加 URL 回退

真实联调暴露出另一类问题：`scout` 给出的候选 URL 不一定可直接抓取。

典型例子：

- 候选名：`OpenAI Codex`
- 某次候选 URL：`https://github.com/openai/codex-cli`
- 页面抓取时返回 `404`

如果不做兜底，整条 `analyst` 链路会因为单个坏链接失败。

因此当前 `ResearchTools.build_evidence_bundle()` 已增加回退逻辑：

1. 优先抓取候选主 URL
2. 如果主 URL 不可达
3. 使用同主题搜索结果
4. 选择第一个可成功抓取的页面作为证据主页面

这保证了：

- `analyst` 更偏向“尽量继续跑”
- 坏链接不再必然终止整轮 deepen

## 4. 当前真实架构

### 4.1 生成侧执行链路

```text
HarnessController
  -> Role
    -> DeepagentsRoleAdapter
      -> ModelInvocation
        -> response_schema_name
        -> response_schema
        -> payload
      -> ModelRunner
        -> DeepSeekRunner
          -> DeepSeek chat/completions API
      -> Pydantic validate
    -> Deterministic Mapper
      -> Domain Models
```

### 4.2 搜索与证据链路

```text
Role
  -> ResearchTools
    -> ExaSearchClient
    -> GitHubSignals
    -> HttpPageExtractor
  -> build_evidence_bundle()
    -> primary url
    -> fallback search hit if primary fails
```

### 4.3 评估链路

评估侧没有模型参与，仍然保持：

- `EvidenceJudge`
- `CoverageJudge`
- `Challenger`
- `StopJudge`

这保证了 stop / continue 决策仍然可解释、可测试、可控。

## 5. 当前关键实现决策

### 5.1 provider/model 继续保持运行时可选

虽然当前真实 provider 只实现了 `DeepSeekRunner`，但以下项没有写死在 role 或 controller 内：

- `provider`
- `model`
- `base_url`
- `api_key_env`
- `timeout_seconds`
- `max_retries`

### 5.2 role 仍只负责生成，不直接生成最终 domain model

模型返回的是中间 schema，而不是最终 domain entities。

本地代码仍然负责：

- ID
- 状态流转
- 默认值
- 时间戳
- deterministic mapping

### 5.3 controller 负责记录生成侧失败

当前行为是：

- `initializer` 失败：直接 fail-fast
- `lead_researcher` 失败：role 内 fallback
- `scout/analyst` 失败：controller 记录 role error 并继续

记录格式包含：

- role name
- provider
- model
- exception type
- exception message

## 6. 当前已完成的验证

### 6.1 本地测试验证

当前版本已通过完整回归：

- `65 passed`

覆盖了：

- runner / factory
- adapter
- schemas / mappers
- roles
- controller
- CLI
- search tools

### 6.2 真实联调验证

已经做过真实 API smoke，不是 mock：

- `DeepSeek` 初始化链路成功
- `DeepSeek + Exa + GitHub` 的 scout 链路成功
- `DeepSeek + 页面抓取 + analyst` 成功
- 状态与报告成功落盘

真实落盘产物示例：

- `/tmp/jingyantai-step-smoke-exa/smoke-step-004/state.json`
- `/tmp/jingyantai-step-smoke-exa/smoke-step-004/artifacts/final-report.json`

## 7. 当前仍然存在的缺口

当前状态是“核心真实链路已跑通”，但还不是“可以放心长期上线稳定跑”。

剩余缺口主要有 4 类：

### 7.1 候选质量控制仍不够强

虽然已经有 analyst 前回退，但还缺：

- URL 规范化
- canonical repo / website 选择
- 可达性预检查
- 候选排序质量约束

### 7.2 可观测性不足

当前还缺：

- role 耗时
- provider 请求耗时
- fallback 触发原因
- 外部抓取失败统计

### 7.3 长程运行控制不足

当前 smoke 已经验证通过，但长程 run 仍需继续强化：

- phase 级 timeout
- 更精细的 budget 消耗统计
- 慢模型阶段的调度策略
- 更好的 retry / degrade 策略

### 7.4 报告质量控制还不够

还缺：

- duplicate competitor merge
- canonical URL 统一
- citation 质量检查
- 结论置信度层级

## 8. 后续阶段建议

从当前状态继续推进，优先顺序建议为：

1. 候选 URL 规范化与可达性筛选
2. trace / metrics / 耗时观测
3. 长程 run 的 budget 与 timeout 管理
4. 最终报告质量提升
5. 真实大预算长跑验证

## 9. 一句话结论

第二阶段的本质目标已经达成：

`竞研台` 已从“有 harness 骨架的本地原型”升级为“生成侧真实接入 LLM、搜索侧真实接入搜索 API、并经过真实 smoke 验证的 agent runtime”。

接下来不再是“是否能跑”的问题，而是“如何把它继续稳定化、观测化、上线化”的问题。
