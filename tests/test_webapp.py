from __future__ import annotations

import json
from pathlib import Path

from jingyantai.domain.models import BudgetPolicy, RunState, RunTrace
from jingyantai.domain.phases import Phase
from jingyantai.storage.run_store import FileRunStore
from jingyantai.webapp import (
    DEFAULT_PORT,
    explain_run_outcome,
    load_report_summary,
    load_raw_artifact,
    make_app,
    server_bind_address_from_env,
)


def test_default_webapp_port_avoids_existing_8090() -> None:
    assert DEFAULT_PORT == 8091


def test_render_port_env_overrides_local_default(monkeypatch) -> None:
    monkeypatch.delenv("JINGYANTAI_WEB_HOST", raising=False)
    monkeypatch.delenv("JINGYANTAI_WEB_PORT", raising=False)
    monkeypatch.setenv("PORT", "10000")

    assert server_bind_address_from_env() == ("0.0.0.0", 10000)


def test_webapp_serves_index_page() -> None:
    app = make_app()
    response = app.get_response("/")

    assert response.status == "200 OK"
    assert "竞研台" in response.body.decode("utf-8")


def test_webapp_accepts_head_health_check() -> None:
    app = make_app()
    response = app.handle_request("HEAD", "/", b"")

    assert response.status == "200 OK"
    assert response.body == b""
    assert response.content_type == "text/html; charset=utf-8"


def test_load_report_summary_reads_final_report(tmp_path: Path) -> None:
    report_dir = tmp_path / "run-demo" / "artifacts"
    report_dir.mkdir(parents=True)
    (report_dir / "final-report.json").write_text(
        json.dumps(
            {
                "target_summary": "Claude Code competitors",
                "confirmed_competitors": ["Aider", "Codex"],
                "key_uncertainties": [{"question": "Pricing details?"}],
                "citations": {"Aider": ["https://aider.chat"]},
            }
        ),
        encoding="utf-8",
    )

    summary = load_report_summary(tmp_path, "run-demo")

    assert summary == {
        "run_id": "run-demo",
        "target_summary": "Claude Code competitors",
        "confirmed_competitors": ["Aider", "Codex"],
        "key_uncertainties": [{"question": "Pricing details?"}],
        "citations": {"Aider": ["https://aider.chat"]},
    }


def test_start_run_returns_immediately_with_running_status(monkeypatch) -> None:
    app = make_app()

    def fake_spawn(target: str) -> str:
        app._status["run-demo"] = {  # type: ignore[attr-defined]
            "run_id": "run-demo",
            "target": target,
            "phase": "expand",
            "round_index": 0,
            "stop_reason": None,
        }
        return "run-demo"

    monkeypatch.setattr(app, "_spawn_run", fake_spawn)

    response = app.handle_request("POST", "/api/run", b'{"target":"Claude Code"}')
    payload = json.loads(response.body.decode("utf-8"))

    assert response.status == "200 OK"
    assert payload["status"] == {
        "run_id": "run-demo",
        "target": "Claude Code",
        "phase": "expand",
        "round_index": 0,
        "stop_reason": None,
    }
    assert payload["progress"] == []


def test_explain_run_outcome_surfaces_stop_reason_and_diagnostics(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.STOP,
        budget=BudgetPolicy(
            max_rounds=4,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        ),
        stop_reason="round budget exhausted: next round 5 exceeds max_rounds=4",
        round_index=4,
    )
    state.traces.append(
        RunTrace(
            round_index=4,
            phase=Phase.EXPAND,
            planner_output="Focus on discovering at least one confirmed direct competitor.",
            dispatched_tasks=[],
            new_candidates=[],
            new_findings=[],
            review_decisions=[],
            stop_or_continue="continue",
            diagnostics=[
                "scout returned zero confirmed candidates",
                "fallback query still produced article pages",
            ],
        )
    )
    store.save_state(state)

    summary = explain_run_outcome(store.load_state("run-1"))

    assert summary["status"] == "已停止，仍未确认出有效竞品"
    assert summary["stop_reason"] == "round budget exhausted: next round 5 exceeds max_rounds=4"
    assert summary["confirmed_count"] == 0
    assert summary["latest_phase"] == "扩展候选"
    assert summary["latest_plan"] == "Focus on discovering at least one confirmed direct competitor."
    assert summary["recent_diagnostics"] == [
        "scout returned zero confirmed candidates",
        "fallback query still produced article pages",
    ]


def test_load_raw_artifact_reads_report_state_and_progress_log(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1" / "artifacts"
    run_dir.mkdir(parents=True)
    (run_dir / "final-report.json").write_text('{"ok": true}', encoding="utf-8")
    (tmp_path / "run-1" / "state.json").write_text('{"state": true}', encoding="utf-8")
    (run_dir / "progress-log.jsonl").write_text('{"step": 1}\n{"step": 2}\n', encoding="utf-8")

    report = load_raw_artifact(tmp_path, "run-1", "report")
    state = load_raw_artifact(tmp_path, "run-1", "state")
    progress = load_raw_artifact(tmp_path, "run-1", "progress")

    assert report == '{"ok": true}'
    assert state == '{"state": true}'
    assert progress == '{"step": 1}\n{"step": 2}'
