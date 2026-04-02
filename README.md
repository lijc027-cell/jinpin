# 竞研台

面向小团队的长程竞品研究 Harness。

## 安装

```bash
pip install -e .[dev]
```

在环境变量或本地 `.env` 中设置所需密钥：

```bash
export DEEPSEEK_API_KEY=your_deepseek_key
export TAVILY_API_KEY=your_tavily_key
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
  --timeout-seconds 20 \
  --max-retries 1
```

如需覆盖运行目录：

```bash
jingyantai run "Claude Code" --runs-dir ./runs/demo
```

## 当前实现

- 生成侧走真实模型链路：`Role -> DeepagentsRoleAdapter -> ModelRunner -> DeepSeekRunner`
- 评估侧保持确定性 Python gate，不和生成侧混用职责
- provider/model/base_url/api_key_env/timeout_seconds/max_retries 可由 CLI 显式覆盖
- run artifact 落盘到本地目录，最终报告保留引用
