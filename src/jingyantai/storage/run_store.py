from __future__ import annotations

import json
from pathlib import Path

from jingyantai.domain.models import FinalReport, RunState, RunTrace


class FileRunStore:
    def __init__(self, root_dir: Path) -> None:
        self._root_dir = Path(root_dir)

    def _run_dir(self, run_id: str) -> Path:
        run_dir = self._root_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def save_state(self, state: RunState) -> None:
        run_dir = self._run_dir(state.run_id)
        (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        (run_dir / "traces").mkdir(parents=True, exist_ok=True)
        state_path = run_dir / "state.json"
        state_path.write_text(state.model_dump_json(indent=2), encoding="utf-8")

    def load_state(self, run_id: str) -> RunState:
        state_path = self._run_dir(run_id) / "state.json"
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        return RunState.model_validate(payload)

    def append_trace(self, run_id: str, trace: RunTrace) -> None:
        traces_dir = self._run_dir(run_id) / "traces"
        traces_dir.mkdir(parents=True, exist_ok=True)
        trace_path = traces_dir / f"{trace.round_index:03d}-{trace.phase.value}.json"
        trace_path.write_text(trace.model_dump_json(indent=2), encoding="utf-8")

    def save_report(self, run_id: str, report: FinalReport) -> None:
        report_path = self._run_dir(run_id) / "artifacts" / "final-report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
