from pathlib import Path

import pytest

from jingyantai.domain.models import BudgetPolicy, FinalReport, RunState, RunTrace
from jingyantai.domain.phases import Phase
from jingyantai.storage.run_store import FileRunStore


def test_run_store_persists_and_loads_state(tmp_path: Path):
    store = FileRunStore(tmp_path)
    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.INITIALIZE,
        budget=BudgetPolicy(max_rounds=4, max_active_candidates=8, max_deepen_targets=3, max_external_fetches=30, max_run_duration_minutes=20),
    )

    store.save_state(state)
    loaded = store.load_state("run-1")

    assert loaded.run_id == "run-1"
    assert loaded.target == "Claude Code"
    assert loaded.current_phase == Phase.INITIALIZE
    assert loaded.budget == state.budget


def test_run_store_appends_trace_files(tmp_path: Path):
    store = FileRunStore(tmp_path)
    trace = RunTrace(
        round_index=0,
        phase=Phase.INITIALIZE,
        planner_output="Create charter",
        dispatched_tasks=[],
        new_candidates=[],
        new_findings=[],
        review_decisions=[],
        stop_or_continue="continue",
    )

    store.append_trace("run-1", trace)

    assert (tmp_path / "run-1" / "traces" / "000-initialize.json").exists()


def test_load_state_missing_run_does_not_create_run_dir(tmp_path: Path):
    store = FileRunStore(tmp_path)

    with pytest.raises(FileNotFoundError):
        store.load_state("missing-run")

    assert not (tmp_path / "missing-run").exists()


def test_save_report_writes_to_artifacts_final_report(tmp_path: Path):
    store = FileRunStore(tmp_path)
    report = FinalReport(
        target_summary="Summary",
        confirmed_competitors=["Comp A"],
        rejected_candidates=["Comp B"],
        comparison_matrix=[{"name": "Comp A", "positioning": "direct"}],
        key_uncertainties=["uncertain pricing"],
        citations={"Comp A": ["https://example.com"]},
    )

    saved_path = store.save_report("run-1", report)

    assert (tmp_path / "run-1" / "artifacts" / "final-report.json").exists()
    assert saved_path == tmp_path / "run-1" / "artifacts" / "final-report.json"
