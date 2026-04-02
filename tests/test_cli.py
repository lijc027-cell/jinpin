from __future__ import annotations

from typer.testing import CliRunner

from jingyantai.cli import app


def test_run_command_passes_llm_settings_to_controller_builder(monkeypatch, tmp_path):
    from jingyantai.domain.models import BudgetPolicy, FinalReport, RunState
    from jingyantai.domain.phases import Phase

    captured = {}

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

    def fake_build_controller(settings):
        captured["provider"] = settings.provider
        captured["model"] = settings.model
        captured["base_url"] = settings.base_url
        captured["api_key_env"] = settings.api_key_env
        captured["timeout_seconds"] = settings.timeout_seconds
        captured["max_retries"] = settings.max_retries
        captured["runs_dir"] = settings.runs_dir
        return FakeController()

    monkeypatch.setattr("jingyantai.cli.build_controller", fake_build_controller)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "run",
            "Claude Code",
            "--provider",
            "deepseek",
            "--model",
            "deepseek-chat",
            "--base-url",
            "https://api.deepseek.com",
            "--api-key-env",
            "DEEPSEEK_API_KEY",
            "--timeout-seconds",
            "12.5",
            "--max-retries",
            "3",
            "--runs-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert captured == {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "timeout_seconds": 12.5,
        "max_retries": 3,
        "runs_dir": tmp_path,
    }
    assert "run-test" in result.stdout
    assert "Claude Code" in result.stdout
    assert "Aider" in result.stdout


def test_run_help_exposes_api_key_env_but_not_plain_api_key():
    runner = CliRunner()

    result = runner.invoke(app, ["run", "--help"])

    assert result.exit_code == 0
    assert "--api-key-env" in result.stdout
    assert "--api-key " not in result.stdout
