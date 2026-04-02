from __future__ import annotations

from typer.testing import CliRunner

from jingyantai.cli import app


def test_run_command_emits_run_id_target_and_confirmed_competitors(monkeypatch, tmp_path):
    from jingyantai.domain.models import BudgetPolicy, FinalReport, RunState
    from jingyantai.domain.phases import Phase

    class FakeController:
        def run(self, target: str, budget: BudgetPolicy):
            state = RunState(run_id="run-test", target=target, current_phase=Phase.STOP, budget=budget)
            state.final_report = FinalReport(
                target_summary="Competitive landscape for Claude Code",
                confirmed_competitors=["Aider", "OpenAI Codex CLI", "OpenCode"],
                rejected_candidates=[],
                comparison_matrix=[],
                key_uncertainties=[],
                citations={"Aider": ["https://aider.chat"]},
            )
            return state

    monkeypatch.setattr("jingyantai.cli.build_controller", lambda settings: FakeController())
    runner = CliRunner()

    result = runner.invoke(app, ["run", "Claude Code", "--runs-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert "run-test" in result.stdout
    assert "Claude Code" in result.stdout
    assert "Aider" in result.stdout
