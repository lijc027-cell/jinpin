from __future__ import annotations

import sys
from pathlib import Path

from jingyantai.domain.models import BudgetPolicy, ResearchBrief, RunCharter, StopDecision
from jingyantai.domain.phases import StopVerdict

# Pytest (importlib mode) does not guarantee the `tests/` dir is importable as a package.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakes import FakeInitializer, FakeStopJudge  # noqa: E402


def test_fake_initializer_run_returns_brief_and_charter():
    brief, charter = FakeInitializer().run("Claude Code")

    assert isinstance(brief, ResearchBrief)
    assert isinstance(brief.budget, BudgetPolicy)
    assert brief.target == "Claude Code"

    assert isinstance(charter, RunCharter)
    assert "Claude Code" in charter.mission


def test_fake_stop_judge_run_returns_stop_decision():
    decision = FakeStopJudge(StopVerdict.CONTINUE).run(None)

    assert isinstance(decision, StopDecision)
    assert decision.verdict == StopVerdict.CONTINUE
