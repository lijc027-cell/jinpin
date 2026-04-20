I'm using the writing-plans skill to create the implementation plan.
# Bootstrap The Project Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bootstrap the jingyantai package so the repo exposes version metadata and a CLI entry point, matching Task 1’s specification.

**Architecture:** Create a minimal package that uses Hatchling for builds, Typer for CLI shell, and exposes metadata from `src/jingyantai` so the test can easily import `__version__` and `app`. This ensures the tests and future commands run against a concrete package structure.

**Tech Stack:** Python 3.12+, Hatchling build backend, Typer CLI, pytest for tests, and Hatchling’s recommended dev-dependencies.

---

### Task 1: Bootstrap Project Skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `README.md`
- Create: `src/jingyantai/__init__.py`
- Create: `src/jingyantai/cli.py`
- Create: `tests/test_bootstrap.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bootstrap.py
from jingyantai import __version__
from jingyantai.cli import app


def test_package_exposes_version_and_cli_name():
    assert __version__ == "0.1.0"
    assert app.info.name == "jingyantai"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src pytest tests/test_bootstrap.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jingyantai'`

- [ ] **Step 3: Write minimal bootstrap implementation**

```toml
# pyproject.toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "jingyantai"
version = "0.1.0"
description = "Long-running competitive research harness for small teams."
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
  "beautifulsoup4>=4.12",
  "httpx>=0.27",
  "pydantic>=2.7",
  "pydantic-settings>=2.2",
  "rich>=13.7",
  "typer>=0.12",
]

[project.optional-dependencies]
deepagents = [
  "deepagents @ git+https://github.com/langchain-ai/deepagents.git",
]
dev = [
  "pytest>=8.2",
  "pytest-cov>=5.0",
]

[project.scripts]
jingyantai = "jingyantai.cli:app"

[tool.pytest.ini_options]
pythonpath = ["src"]
```

```gitignore
# .gitignore
.env
.venv
__pycache__
.pytest_cache
*.pyc
runs
dist
build
```

```env
# .env.example
MODEL_PROVIDER=anthropic
MODEL_NAME=claude-3-7-sonnet-latest
TAVILY_API_KEY=
GITHUB_TOKEN=
RUNS_DIR=./runs
```

```markdown
# README.md

# 竞研台

面向小团队的长程竞品研究 Harness。

## Current Scope

- `Claude Code` 竞品研究 MVP
- 长程运行直到 `Stop Judge` 放行
- 生成侧与评估侧严格分离

## Planned Commands

```bash
pip install -e .[dev]
jingyantai --help
```
```

```python
# src/jingyantai/__init__.py
__version__ = "0.1.0"
```

```python
# src/jingyantai/cli.py
import typer

app = typer.Typer(name="jingyantai", no_args_is_help=True)


@app.callback()
def main() -> None:
    """竞研台 CLI."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src pytest tests/test_bootstrap.py -v`
Expected: PASS with `1 passed`

- [ ] **Step 5: Commit bootstrap scaffolding**

```bash
git init
PYTHONPATH=src git add pyproject.toml .gitignore .env.example README.md src/jingyantai/__init__.py src/jingyantai/cli.py tests/test_bootstrap.py
git commit -m "chore: bootstrap jingyantai package"
```
