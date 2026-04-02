# 竞研台

面向小团队的长程竞品研究 Harness。

## Setup

```bash
pip install -e .[dev]
```

可选：在环境变量或本地 `.env` 中设置 `TAVILY_API_KEY` 和 `GITHUB_TOKEN`。

## Run

```bash
jingyantai run "Claude Code"
```

## MVP Properties

- Long-running harness with explicit phases
- Generator/evaluator separation
- File-backed run artifacts
- Cited final report
