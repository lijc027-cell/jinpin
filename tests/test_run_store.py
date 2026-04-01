from pathlib import Path

from jingyantai.domain.models import BudgetPolicy, RunState, RunTrace
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
