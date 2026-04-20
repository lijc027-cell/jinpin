from __future__ import annotations

import os
import subprocess
import sys

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


def test_run_command_hydrates_provider_api_key_from_dotenv_when_env_is_missing(monkeypatch, tmp_path):
    from jingyantai.domain.models import BudgetPolicy, FinalReport, RunState
    from jingyantai.domain.phases import Phase

    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "\n".join(
            [
                "PROVIDER=deepseek",
                "MODEL=deepseek-chat",
                "BASE_URL=https://api.deepseek.com",
                "API_KEY_ENV=DEEPSEEK_API_KEY",
                "DEEPSEEK_API_KEY=from-dotenv",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    captured = {}

    class FakeController:
        def run(self, target: str, budget: BudgetPolicy):
            state = RunState(run_id="run-test", target=target, current_phase=Phase.STOP, budget=budget)
            state.final_report = FinalReport(
                target_summary="Competitive landscape for Claude Code",
                confirmed_competitors=["Aider"],
                rejected_candidates=[],
                comparison_matrix=[],
                key_uncertainties=[],
                citations={"Aider": ["https://aider.chat"]},
            )
            return state

    def fake_build_controller(settings):
        captured["api_key_env"] = settings.api_key_env
        captured["provider_api_key"] = os.getenv(settings.api_key_env)
        return FakeController()

    monkeypatch.setattr("jingyantai.cli.build_controller", fake_build_controller)
    runner = CliRunner()

    result = runner.invoke(app, ["run", "Claude Code"])

    assert result.exit_code == 0
    assert captured == {
        "api_key_env": "DEEPSEEK_API_KEY",
        "provider_api_key": "from-dotenv",
    }


def test_run_command_persists_generated_final_report_artifacts(monkeypatch, tmp_path):
    from jingyantai.domain.models import BudgetPolicy, FinalReport, RunState
    from jingyantai.domain.phases import Phase
    from jingyantai.storage.run_store import FileRunStore

    final_report = FinalReport(
        target_summary="Competitive landscape for Claude Code",
        confirmed_competitors=["Aider"],
        rejected_candidates=[],
        comparison_matrix=[],
        key_uncertainties=[],
        citations={"Aider": ["https://aider.chat"]},
    )

    class FakeController:
        def __init__(self) -> None:
            self.store = FileRunStore(tmp_path)

        def run(self, target: str, budget: BudgetPolicy):
            return RunState(run_id="run-test", target=target, current_phase=Phase.STOP, budget=budget)

    class FakeSynthesizer:
        def run(self, state: RunState) -> FinalReport:
            return final_report

    class FakeCitationAgent:
        def run(self, state: RunState, draft: FinalReport) -> FinalReport:
            return draft

    monkeypatch.setattr("jingyantai.cli.build_controller", lambda settings: FakeController())
    monkeypatch.setattr("jingyantai.cli.Synthesizer", lambda: FakeSynthesizer())
    monkeypatch.setattr("jingyantai.cli.CitationAgent", lambda: FakeCitationAgent())
    runner = CliRunner()

    result = runner.invoke(app, ["run", "Claude Code", "--runs-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert (tmp_path / "run-test" / "artifacts" / "final-report.json").exists()
    saved_state = FileRunStore(tmp_path).load_state("run-test")
    assert saved_state.final_report == final_report


def test_build_controller_wires_default_contract_builder(monkeypatch, tmp_path):
    import jingyantai.cli as cli

    captured = {}

    class SpyHarnessController:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    class Dummy:
        def __init__(self, *args, **kwargs) -> None:
            pass

    monkeypatch.setattr(cli, "HarnessController", SpyHarnessController)
    monkeypatch.setattr(cli, "ResearchTools", lambda **kwargs: object())
    monkeypatch.setattr(cli, "ExaSearchClient", lambda *args, **kwargs: object())
    monkeypatch.setattr(cli, "HttpPageExtractor", lambda *args, **kwargs: object())
    monkeypatch.setattr(cli, "GitHubSignals", lambda *args, **kwargs: object())
    monkeypatch.setattr(cli, "build_model_runner", lambda *args, **kwargs: object())
    monkeypatch.setattr(cli, "DeepagentsRoleAdapter", Dummy)
    monkeypatch.setattr(cli, "InitializerRole", Dummy)
    monkeypatch.setattr(cli, "LeadResearcherRole", Dummy)
    monkeypatch.setattr(cli, "ScoutRole", Dummy)
    monkeypatch.setattr(cli, "AnalystRole", Dummy)
    monkeypatch.setattr(cli, "EvidenceJudge", Dummy)
    monkeypatch.setattr(cli, "CoverageJudge", Dummy)
    monkeypatch.setattr(cli, "Challenger", Dummy)
    monkeypatch.setattr(cli, "StopJudge", Dummy)
    monkeypatch.setattr(cli, "get_role_prompt", lambda *args, **kwargs: "")

    settings = type(
        "SettingsLike",
        (),
        {
            "provider": "dummy",
            "model": "dummy-model",
            "base_url": "https://example.invalid",
            "api_key_env": "DUMMY_KEY",
            "timeout_seconds": 1.0,
            "max_retries": 0,
            "runs_dir": tmp_path / "runs",
            "exa_api_key": "dummy-exa",
            "github_token": None,
        },
    )()

    cli.build_controller(settings)

    assert "contract_builder" in captured
    assert captured["contract_builder"] is not None

    from jingyantai.domain.models import BudgetPolicy, RunState
    from jingyantai.domain.phases import Phase
    from jingyantai.runtime.contracts import ContractJudge

    contract = captured["contract_builder"].build(
        RunState(
            run_id="run-test",
            target="Claude Code",
            current_phase=Phase.INITIALIZE,
            budget=BudgetPolicy(
                max_rounds=0,
                max_active_candidates=8,
                max_deepen_targets=3,
                max_external_fetches=30,
                max_run_duration_minutes=20,
            ),
        )
    )
    assert ContractJudge().run(contract).is_valid


def test_run_command_reports_forced_stop_reason(monkeypatch, tmp_path):
    from jingyantai.domain.models import BudgetPolicy, FinalReport, RunState
    from jingyantai.domain.phases import Phase
    from jingyantai.storage.run_store import FileRunStore

    class FakeController:
        def __init__(self) -> None:
            self.store = FileRunStore(tmp_path)

        def run(self, target: str, budget: BudgetPolicy):
            state = RunState(run_id="run-test", target=target, current_phase=Phase.STOP, budget=budget)
            state.stop_reason = "forced_stop_due_to_budget"
            state.final_report = FinalReport(
                target_summary="Competitive landscape for Claude Code",
                confirmed_competitors=["Aider"],
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
    assert "stop_reason=forced_stop_due_to_budget" in result.stdout


def test_resume_command_uses_controller_resume(monkeypatch, tmp_path):
    from jingyantai.domain.models import BudgetPolicy, FinalReport, RunState
    from jingyantai.domain.phases import Phase

    captured = {}

    class FakeController:
        def resume(self, run_id: str, budget: BudgetPolicy):
            captured["run_id"] = run_id
            captured["budget"] = budget
            state = RunState(run_id=run_id, target="Claude Code", current_phase=Phase.STOP, budget=budget)
            state.final_report = FinalReport(
                target_summary="Competitive landscape for Claude Code",
                confirmed_competitors=["Aider"],
                rejected_candidates=[],
                comparison_matrix=[],
                key_uncertainties=[],
                citations={"Aider": ["https://aider.chat"]},
            )
            return state

    monkeypatch.setattr("jingyantai.cli.build_controller", lambda settings: FakeController())
    runner = CliRunner()

    result = runner.invoke(app, ["resume", "run-test", "--runs-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert captured["run_id"] == "run-test"
    assert captured["budget"].max_rounds == 4
    assert "run-test" in result.stdout


def test_cancel_command_persists_cancel_request(tmp_path):
    from jingyantai.storage.run_store import FileRunStore

    runner = CliRunner()
    result = runner.invoke(app, ["cancel", "run-test", "--runs-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert FileRunStore(tmp_path).load_cancel_request("run-test") == "cancelled by user"
    assert "run-test" in result.stdout


def test_python_m_cli_exposes_help():
    env = os.environ.copy()
    env["PYTHONPATH"] = "/Users/l/Downloads/projects/竞品/src"

    result = subprocess.run(
        [sys.executable, "-m", "jingyantai.cli", "--help"],
        cwd="/Users/l/Downloads/projects/竞品",
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "竞研台 CLI" in result.stdout
    assert "run" in result.stdout
