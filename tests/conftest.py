from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest


# Ensure our repository root is first on sys.path so `import tests.*` resolves
# to this repo's `tests/` (not a third-party package also named `tests`).
_ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT_DIR))

_TESTS_DIR = Path(__file__).resolve().parent
_tests_mod = sys.modules.get("tests")
if _tests_mod is None or str(_TESTS_DIR) not in list(getattr(_tests_mod, "__path__", [])):
    pkg = ModuleType("tests")
    pkg.__path__ = [str(_TESTS_DIR)]
    sys.modules["tests"] = pkg


@pytest.fixture
def runs_dir(tmp_path: Path) -> Path:
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    return runs
