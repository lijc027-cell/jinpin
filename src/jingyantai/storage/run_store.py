from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jingyantai.domain.models import FinalReport, RunState, RunTrace


class FileRunStore:
    def __init__(self, root_dir: Path) -> None:
        self._root_dir = Path(root_dir)

    def _run_dir(self, run_id: str) -> Path:
        return self._root_dir / run_id

    def save_state(self, state: RunState) -> None:
        run_dir = self._run_dir(state.run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        (run_dir / "traces").mkdir(parents=True, exist_ok=True)
        state_path = run_dir / "state.json"
        state_path.write_text(state.model_dump_json(indent=2), encoding="utf-8")

    def load_state(self, run_id: str) -> RunState:
        state_path = self._run_dir(run_id) / "state.json"
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        return RunState.model_validate(payload)

    def append_trace(self, run_id: str, trace: RunTrace) -> None:
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        traces_dir = run_dir / "traces"
        traces_dir.mkdir(parents=True, exist_ok=True)
        trace_path = traces_dir / f"{trace.round_index:03d}-{trace.phase.value}.json"
        trace_path.write_text(trace.model_dump_json(indent=2), encoding="utf-8")

    def save_report(self, run_id: str, report: FinalReport) -> Path:
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        report_path = run_dir / "artifacts" / "final-report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return report_path

    def save_round_contract(self, run_id: str, round_index: int, payload: Any) -> Path:
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = run_dir / "artifacts" / f"round-contract-{round_index:03d}.json"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        if hasattr(payload, "model_dump_json"):
            artifact_path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
        else:
            artifact_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return artifact_path

    def save_research_spec(self, run_id: str, payload: Any) -> Path:
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = run_dir / "artifacts" / "research-spec.json"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        if hasattr(payload, "model_dump_json"):
            artifact_path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
        else:
            artifact_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return artifact_path

    def append_progress_log(self, run_id: str, payload: Any) -> Path:
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        log_path = run_dir / "artifacts" / "progress-log.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        if hasattr(payload, "model_dump"):
            record = payload.model_dump(mode="json")
        else:
            record = payload

        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")
        return log_path

    def append_evaluator_log(self, run_id: str, payload: Any) -> Path:
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        log_path = run_dir / "artifacts" / "evaluator-log.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        if hasattr(payload, "model_dump"):
            record = payload.model_dump(mode="json")
        else:
            record = payload

        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")
        return log_path

    def request_cancel(self, run_id: str, *, reason: str = "cancelled by user") -> Path:
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = run_dir / "artifacts" / "cancel-request.json"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(json.dumps({"reason": reason}, ensure_ascii=False, indent=2), encoding="utf-8")
        return artifact_path

    def load_cancel_request(self, run_id: str) -> str | None:
        artifact_path = self._run_dir(run_id) / "artifacts" / "cancel-request.json"
        if not artifact_path.exists():
            return None
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        reason = str(payload.get("reason", "")).strip()
        return reason or "cancelled by user"

    def clear_cancel_request(self, run_id: str) -> None:
        artifact_path = self._run_dir(run_id) / "artifacts" / "cancel-request.json"
        if artifact_path.exists():
            artifact_path.unlink()
