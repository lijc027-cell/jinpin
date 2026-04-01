from __future__ import annotations

import sys
from pathlib import Path

import pytest


# Ensure the repo's `tests/` directory is importable so `from fakes import ...` is stable
# and does not depend on a potentially-conflicting external `tests` package name.
sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture
def runs_dir(tmp_path: Path) -> Path:
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    return runs
