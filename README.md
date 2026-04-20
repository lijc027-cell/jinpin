# 竞研台

面向小团队的长程竞品研究 Harness。

## 安装

```bash
pip install -e .[dev]
```

在环境变量或本地 `.env` 中设置所需密钥：

```bash
export DEEPSEEK_API_KEY=your_deepseek_key
export EXA_API_KEY=your_exa_key
export GITHUB_TOKEN=your_github_token
```

`DEEPSEEK_API_KEY` 是第一版默认生成侧 provider。CLI 只接收 `--api-key-env`，不会接收或输出明文 API key。

## 运行

```bash
jingyantai run "Claude Code" \
  --provider deepseek \
  --model deepseek-chat \
  --base-url https://api.deepseek.com \
  --api-key-env DEEPSEEK_API_KEY \
  --timeout-seconds 60 \
  --max-retries 1
```

如需覆盖运行目录：

```bash
jingyantai run "Claude Code" --runs-dir ./runs/demo
```

恢复上一次 checkpoint：

```bash
jingyantai resume run-20260406025114-abcdef --runs-dir ./runs/demo
```

请求取消一个正在运行或待恢复的 run：

```bash
jingyantai cancel run-20260406025114-abcdef --runs-dir ./runs/demo
```

## 最小 Web 体验

这个项目也提供了一个最小本地 Web 界面，方便直接体验运行效果：

```bash
PYTHONPATH=src python -m jingyantai.webapp
```

默认地址：

```text
http://127.0.0.1:8091
```

如需改端口：

```bash
JINGYANTAI_WEB_PORT=8092 PYTHONPATH=src python -m jingyantai.webapp
```

## 部署到 Render

仓库根目录已包含 `render.yaml`，可直接在 Render 使用 Blueprint 部署。

1. 将项目推送到 GitHub。
2. 在 Render 选择 `New` -> `Blueprint`，连接该 GitHub 仓库。
3. 部署前在 Render 环境变量中填写 `DEEPSEEK_API_KEY`、`EXA_API_KEY`、`GITHUB_TOKEN`。
4. Render 会执行 `pip install -e .`，并用 `python -m jingyantai.webapp` 启动 Web 服务。

Render 会自动注入 `PORT`。Web 服务在检测到 `PORT` 时会监听 `0.0.0.0:$PORT`；本地默认仍是 `127.0.0.1:8091`。

## 当前实现

- 生成侧走真实模型链路：`Role -> DeepagentsRoleAdapter -> ModelRunner -> DeepSeekRunner`
- 搜索侧默认走 Exa Web Search
- 控制面已补齐第一版 `RuntimePolicy` / `RoundContract` / `StopBar` 模型，并保持生成侧与评估侧严格分离
- scout 阶段会做候选 URL 规范化，并优先保留官网根域名候选而不是 docs/blog 子页面
- scout 阶段现在会对 web 候选做 URL 预检查，明显不可达的 docs/blog 页面不会继续进入 deepen；预检查会使用更短的 `page_extract` timeout cap，避免慢 precheck 直接拖长 `expand`
- scout 阶段现在会直接跳过明显 article/review/research 类页面，并在“`target competitor hypothesis` 只打回文章页”时回退到更泛化的 `hypothesis` 查询，先把 raw candidate 源质量拉回产品入口
- analyst 在主 URL 不可达时会回退到搜索命中的可抓取页面
- evidence bundle 现在会按维度优先选更合适的入口页：`workflow` 倾向 docs/guide，`pricing or access` 倾向 pricing/plans
- 同一个已知失败的主 URL 现在会进入 failed `page_extract` cache，避免在后续 bundle / round / role 中重复外部抓取同一失败页面
- 同一个 timeout 后已成功 fallback 的主 URL，现在也会复用已解析出的 fallback 页面，而不是在后续 round / role 中继续重试同一个慢主 URL
- GitHub 仓库信号已补强到 `forks / open_issues / latest_release / latest_commit` 级别，并参与候选排序
- 评估侧保持确定性 Python gate，不和生成侧混用职责
- judge / contract 路径已共享默认 `QualityRubric`，用于 evidence 阈值、默认维度、contract rejection rules，以及结构化 `calibration_examples`
- `LeadResearcher / Scout / Analyst` 的 prompt 与 payload 现在都会显式消费 `quality_rubric / memory_snapshot / historical_memory / watchlist`；prompt 不再只依赖第一版 good/bad pattern，也会渲染 shared rubric 里的 `pass / fail / edge_case` calibration sample
- `LeadResearcher / Scout / Analyst` 现在会把 `gap_tickets + watchlist + repeated failure patterns` 收缩成 `execution_focus`，驱动下一轮只围绕当前瓶颈推进
- prompt 已明确约束 lead 产出“能关闭命名 gap 的最小下一步”，scout / analyst 会优先处理当前 gap ticket 指向的缺口
- `StopJudge` 现在除了 confirmed hard gate，还会检查 `coverage ratio` 与 `high-impact uncertainties`，并为 `open_questions / uncertainties` 生成更具体的目标范围 ticket
- provider/model/base_url/api_key_env/timeout_seconds/max_retries 可由 CLI 显式覆盖
- controller 会记录 phase 耗时、role 耗时、搜索与抓取耗时、fallback 诊断信息
- controller 会在初始化完成后落盘 run 级 `research-spec.json`
- controller 会持续追加 `evaluator-log.jsonl`，记录 review decision、stop decision、forced stop 和 contract rejection
- controller 现在会为每一轮落盘 `round-contract-000.json` 这类 handoff artifact，并持续追加 `progress-log.jsonl`
- controller 已接入 `phase soft timeout`，并会把 phase deadline 透传到 `ResearchTools / search / page_extract / github`；晚启动的 external fetch 会被跳过，而不是继续无界拉长 phase
- deepen 阶段现在也会像 expand 一样按剩余 analyst 槽位切分 phase budget，避免单个 analyst 直接吃完整段 phase 窗口
- controller 会记录 external fetch 的细分来源统计，例如 `search / github_lookup / page_extract`
- 不同错误类型现在会进入不同控制路径：重试、降级、跳过或整 phase 失败
- run 会跟踪外部抓取预算与总运行时长预算，超限后自动停止
- forced stop 会把具体 `stop_reason` 写入 `state.json`、progress log 和 CLI 输出
- 新 run 的 `run_id` 现在包含更细时间粒度和随机后缀，不再依赖秒级时间戳
- controller 已支持基于 checkpoint 的 `resume / recovery`，会按持久化的 resume cursor 从下一安全 phase 继续，而不是强制重头开始
- CLI 已提供显式 `resume` / `cancel` 入口；`cancel` 会写入 cancel request，并在后续 phase 边界生效
- final report 现在会输出带 `coverage / confidence_band` 的 comparison matrix、标准化 uncertainty 文本，以及经过质量筛选和排序的 citations
- `python -m jingyantai.cli` 入口已可直接用于 smoke / 本地调试运行
- DeepSeek runner 现在会把 `invocation.timeout_seconds` 当作整次模型调用的总重试预算，而不是每次 retry 都重给一遍 timeout，避免 `LeadResearcher / Scout` 把 phase deadline 乘大
- controller 现在会在启动时加载 `_global/latest-snapshot.json` 到共享上下文，并在结束后回写 `_global/latest-snapshot.json` / `_global/watchlist.json` / `_global/memory.json`
- watchlist / memory 不再只是空骨架，当前已会从 gap ticket 和 coverage review 中提取“下一轮还要补什么”
- controller 现在还会从 `_global/memory.json` 汇总同 target 的 `historical_memory`，把 recent runs、recurring competitors、recurring trusted sources、recurring failure patterns 注入生成侧
- run artifact 落盘到本地目录，最终报告保留引用

## 第一版边界

第一版当前成立的是：

- 本地 CLI 驱动的单用户竞品研究 harness
- 可选 `provider / model / base_url / api_key_env`
- 多轮运行、生成评估分离、带 memory/watchlist 的研究闭环
- 本地 artifacts 与最终报告落盘

第一版当前不包含：

- Web 前端
- 多用户 / 多租户
- 分布式队列与跨进程恢复
- 自动调度 / 周期重跑
- judge 模型化
- 多 provider 并行执行

## 验证基线

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q`
  - 当前 fresh 结果：`183 passed`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_controller.py`
  - 当前 fresh 结果：`30 passed`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_research_tools.py`
  - 当前 fresh 结果：`35 passed`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_cli.py`
  - 当前 fresh 结果：`9 passed`
- 已有一轮完整真实 micro smoke 成功结束并自然落盘 control-plane artifacts：
  - `state.json`
  - `artifacts/final-report.json`
  - `artifacts/research-spec.json`
  - `artifacts/evaluator-log.jsonl`
  - `artifacts/round-contract-000.json`
  - `artifacts/progress-log.jsonl`
  - `_global/latest-snapshot.json`
  - `_global/watchlist.json`
  - `_global/memory.json`
- 当前可复查样本：
  - `/tmp/jingyantai-micro-smoke-20260403/run-20260403040432`
  - `/tmp/jingyantai-micro-smoke-20260403/_global`
  - `/tmp/jingyantai-phase4-smoke-20260406-rerun/run-20260405162759`
  - `/tmp/jingyantai-phase4-soft-timeout-20260406/run-20260406025114`
  - `/tmp/jingyantai-phase5-page-extract-smoke-20260406-rerun/run-20260406122352492650-527dc6`
  - `/tmp/jingyantai-phase5-timeout-cache-smoke-20260407/run-20260406162816603503-3013b4`
  - `/tmp/jingyantai-phase6-candidate-filter-20260415/run-20260415134558759852-068412`
  - `/tmp/jingyantai-phase6-query-fallback-20260415/run-20260415140646032795-8b27d8`
  - `/tmp/jingyantai-phase6-timeout-budget-fix-20260415/run-20260416075645295038-be0353`
- 截至 2026-04-07，`phase soft timeout`、更细 fetch breakdown、watchlist/memory richer extraction、`execution_focus` 注入、`StopJudge` stricter stop gate、报告层标准化交付、`python -m` CLI 入口、round budget/forced stop 语义 已通过自动化回归验证
- 2026-04-06 fresh smoke 已验证：
  - `python -m jingyantai.cli run ...` 可直接启动真实链路
  - run 会在预算超限时显式写入 `stop_reason`
  - final report 的维度与 citation 已比上一轮更稳定
  - trace 中已出现 `phase runtime deadline exceeded before external fetch`，说明 tool-layer deadline 传播已经生效
- 2026-04-06 当日晚些时候又补了两项 `page_extract` 收敛：
  - 已知失败 URL 会进入 failed extract cache，避免重复消耗 external fetch budget
  - URL 预检查改为使用更短 timeout cap，减少 `expand` 阶段被慢 precheck 拖尾
- 2026-04-06 最新 fresh smoke `run-20260406122352492650-527dc6` 已验证：
  - run 不再因为 `external fetch budget exceeded` 提前中止，而是正常推进到 `max_rounds=4` 后以 `round budget exhausted` 停止
  - `external_fetch_count` 从旧样本 `47` 降到 `15`
  - `external_fetch_breakdown.page_extract` 从旧样本 `43` 降到 `10`
  - `expand` 阶段 `page_extract` 耗时从旧样本 `43811ms` 降到 `17205ms`
- 2026-04-07 最新 fresh smoke `run-20260406162816603503-3013b4` 已验证：
  - run 继续以 `round budget exhausted` 正常停止，没有退化回 `external fetch budget exceeded`
  - `external_fetch_count` 从上一 fresh 样本 `15` 进一步降到 `10`
  - `external_fetch_breakdown` 从上一 fresh 样本 `search=2, page_extract=10, github_lookup=3` 收敛到 `search=2, page_extract=7, github_lookup=1`
  - 上一 fresh 样本里跨 round 反复出现的 timeout fallback，本次只在 `round 2` 出现 1 次：`primary extract failed: The read operation timed out; fallback to github search hit https://opencode.ai/docs/github`
- 2026-04-15/16 phase-6 smoke 已验证：
  - `run-20260415134558759852-068412` 中，article/review 过滤已把 `page_extract` 从上一样本 `14` 次进一步压到 `6` 次，总外部抓取从 `33` 次降到 `25` 次；停止原因保持为 `round budget exhausted`，不再被 fetch budget 打停
  - `run-20260415140646032795-8b27d8` 中，query fallback + cache 让外部抓取进一步收敛到 `4` 次，但也暴露出新的真实瓶颈：`LeadResearcherRole` 的 invocation timeout 会被 DeepSeek retry 乘大，导致多个 `expand` round 几乎只剩 lead 在跑
  - `run-20260416075645295038-be0353` 中，总 timeout budget 修正已把 expand round 的 lead 耗时从上一样本的 `7.5s / 41.4s / 32.8s / 19.8s / 46.5s` 收敛到 `1.4s / 2.1s / 15.1s / 1.3s / 1.1s`，并把 `expand` 的 soft-timeout 超限收敛到 `39.365s / 30.122s / 30.023s / <=30s / <=30s`
- 当前仍观察到的 residual gap：
  - `phase soft timeout` 仍是协作式控制，已经启动的慢搜索/抓取调用还不能被强制打断，所以 `expand` 仍可能略微超出 `30s`
  - 最新 fresh smoke 虽然已经不再被 fetch budget 打停，但仍然出现 `0 candidates / 0 findings`，说明当前主瓶颈已从 timeout/fetch 收敛转移到 `raw_candidates -> scout candidate selection` 这条链路
  - 因为还没有 confirmed candidate，`deepen / challenge / report` 目前拿到的是空输入；下一步应该优先补“scout 空结果时的 harness fallback 或更强 candidate selection 校准”，而不是继续加更多 fetch/timeout 组件
