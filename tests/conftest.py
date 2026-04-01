from __future__ import annotations

import sys
from pathlib import Path

import pytest


# Ensure repo root is importable so `from tests.fakes import ...` works under pytest importlib mode.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def runs_dir(tmp_path: Path) -> Path:
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    return runs
