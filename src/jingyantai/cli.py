from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from jingyantai.agents.deepagents_adapter import DeepagentsRoleAdapter
from jingyantai.agents.prompts import get_role_prompt
from jingyantai.agents.roles import AnalystRole, InitializerRole, LeadResearcherRole, ScoutRole
from jingyantai.config import Settings, hydrate_runtime_secret
from jingyantai.domain.models import BudgetPolicy, RunProgressEvent
from jingyantai.llm.contracts import ProviderConfig
from jingyantai.llm.factory import build_model_runner
from jingyantai.runtime.compactor import ContextCompactor
from jingyantai.runtime.contracts import ContractJudge, RoundContract
from jingyantai.runtime.controller import HarnessController
from jingyantai.runtime.judges import Challenger, CoverageJudge, EvidenceJudge, StopJudge
from jingyantai.runtime.memory import FileMemoryStore
from jingyantai.runtime.policies import QualityRubric
from jingyantai.runtime.reporting import CitationAgent, Synthesizer
from jingyantai.storage.run_store import FileRunStore
from jingyantai.tools.github_signals import GitHubSignals
from jingyantai.tools.page_extract import HttpPageExtractor
from jingyantai.tools.research_tools import ResearchTools
from jingyantai.tools.web_search import ExaSearchClient

app = typer.Typer(name="jingyantai", no_args_is_help=True)
console = Console()


def _default_budget() -> BudgetPolicy:
    return BudgetPolicy(
        max_rounds=4,
        max_active_candidates=8,
        max_deepen_targets=3,
        max_external_fetches=30,
        max_run_duration_minutes=20,
    )


def _apply_settings_overrides(
    settings: Settings,
    *,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key_env: str | None = None,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
    runs_dir: Path | None = None,
) -> Settings:
    if provider is not None:
        settings.provider = provider
    if model is not None:
        settings.model = model
    if base_url is not None:
        settings.base_url = base_url
    if api_key_env is not None:
        settings.api_key_env = api_key_env
    if timeout_seconds is not None:
        settings.timeout_seconds = timeout_seconds
    if max_retries is not None:
        settings.max_retries = max_retries
    if runs_dir is not None:
        settings.runs_dir = runs_dir
    return settings


def _build_provider_config(settings: Settings) -> ProviderConfig:
    return ProviderConfig(
        provider=settings.provider,
        model=settings.model,
        base_url=settings.base_url,
        api_key_env=settings.api_key_env,
        timeout_seconds=settings.timeout_seconds,
        max_retries=settings.max_retries,
    )


def _console_progress_reporter(event: RunProgressEvent) -> None:
    stage_label = "开始" if event.stage == "start" else "完成"
    stop_reason = ""
    if event.stage == "end" and event.stop_reason:
        stop_reason = f" stop_reason={event.stop_reason}"
    console.print(
        "[dim]"
        f"{event.run_id}"
        "[/dim] "
        f"{stage_label} {event.phase.value} | "
        f"round={event.round_index} "
        f"candidates={event.candidate_count} "
        f"findings={event.finding_count} "
        f"fetches={event.external_fetch_count}{stop_reason} | "
        f"{event.message}"
    )


class _DefaultContractBuilder:
    def build(self, state: object) -> RoundContract:
        target = str(getattr(state, "target", "")).strip() or "target product"
        return RoundContract(
            target_scope="confirmed candidates",
            goal_cluster=f"resolve access and pricing signals for {target}",
            must_answer_questions=["How is access exposed?"],
            required_evidence_types=["official"],
            hard_checks=["must cite official source"],
            done_definition="At least one official access or pricing finding is captured for a confirmed candidate.",
            fallback_plan="If official access or pricing details cannot be found, record as an uncertainty and proceed.",
        )


def build_controller(settings: Settings) -> HarnessController:
    tools = ResearchTools(
        search_client=ExaSearchClient(settings.exa_api_key),
        page_extractor=HttpPageExtractor(),
        github_signals=GitHubSignals(settings.github_token or None),
    )
    runner = build_model_runner(_build_provider_config(settings))
    rubric = QualityRubric.default()
    return HarnessController(
        store=FileRunStore(settings.runs_dir),
        initializer=InitializerRole(
            adapter=DeepagentsRoleAdapter(role_prompt=get_role_prompt("initializer", rubric=rubric), runner=runner)
        ),
        lead_researcher=LeadResearcherRole(
            adapter=DeepagentsRoleAdapter(role_prompt=get_role_prompt("lead_researcher", rubric=rubric), runner=runner),
            quality_rubric=rubric,
        ),
        scouts=[
            ScoutRole(
                tools=tools,
                adapter=DeepagentsRoleAdapter(
                    role_prompt=get_role_prompt("scout_positioning", rubric=rubric), runner=runner
                ),
                hypothesis="terminal coding agent",
                role_name="scout_positioning",
                quality_rubric=rubric,
            ),
            ScoutRole(
                tools=tools,
                adapter=DeepagentsRoleAdapter(role_prompt=get_role_prompt("scout_github", rubric=rubric), runner=runner),
                hypothesis="repo-aware coding agent",
                role_name="scout_github",
                quality_rubric=rubric,
            ),
            ScoutRole(
                tools=tools,
                adapter=DeepagentsRoleAdapter(role_prompt=get_role_prompt("scout_heat", rubric=rubric), runner=runner),
                hypothesis="developer CLI agent",
                role_name="scout_heat",
                quality_rubric=rubric,
            ),
        ],
        analysts=[
            AnalystRole(
                tools=tools,
                adapter=DeepagentsRoleAdapter(
                    role_prompt=get_role_prompt("analyst_positioning", rubric=rubric), runner=runner
                ),
                dimension="positioning",
                role_name="analyst_positioning",
                quality_rubric=rubric,
            ),
            AnalystRole(
                tools=tools,
                adapter=DeepagentsRoleAdapter(
                    role_prompt=get_role_prompt("analyst_workflow", rubric=rubric), runner=runner
                ),
                dimension="workflow",
                role_name="analyst_workflow",
                quality_rubric=rubric,
            ),
            AnalystRole(
                tools=tools,
                adapter=DeepagentsRoleAdapter(role_prompt=get_role_prompt("analyst_pricing", rubric=rubric), runner=runner),
                dimension="pricing or access",
                role_name="analyst_pricing",
                quality_rubric=rubric,
            ),
        ],
        compactor=ContextCompactor(),
        evidence_judge=EvidenceJudge(rubric=rubric),
        coverage_judge=CoverageJudge(rubric=rubric),
        challenger=Challenger(),
        stop_judge=StopJudge(rubric=rubric),
        contract_builder=_DefaultContractBuilder(),
        contract_judge=ContractJudge(rubric=rubric),
        quality_rubric=rubric,
        memory_store=FileMemoryStore(settings.runs_dir),
        progress_reporter=_console_progress_reporter,
    )


def _persist_final_artifacts(controller: object, state: object) -> None:
    report = getattr(state, "final_report", None)
    if report is None:
        return

    store = getattr(controller, "store", None)
    save_state = getattr(store, "save_state", None)
    if callable(save_state):
        save_state(state)

    save_report = getattr(store, "save_report", None)
    if callable(save_report):
        save_report(getattr(state, "run_id"), report)


@app.command()
def run(
    target: str,
    provider: str | None = typer.Option(default=None, help="LLM provider name."),
    model: str | None = typer.Option(default=None, help="LLM model identifier."),
    base_url: str | None = typer.Option(default=None, help="Provider base URL."),
    api_key_env: str | None = typer.Option(default=None, help="Environment variable name for provider API key."),
    timeout_seconds: float | None = typer.Option(default=None, help="Provider request timeout in seconds."),
    max_retries: int | None = typer.Option(default=None, help="Provider request retry count."),
    runs_dir: Path | None = typer.Option(default=None, help="Override run artifact directory."),
) -> None:
    settings = _apply_settings_overrides(
        Settings(),
        provider=provider,
        model=model,
        base_url=base_url,
        api_key_env=api_key_env,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        runs_dir=runs_dir,
    )

    hydrate_runtime_secret(settings.api_key_env)
    controller = build_controller(settings)
    state = controller.run(target=target, budget=_default_budget())
    if state.final_report is None:
        draft = Synthesizer().run(state)
        state.final_report = CitationAgent().run(state, draft)
    _persist_final_artifacts(controller, state)

    console.print(f"run_id={state.run_id}")
    console.print(f"target={state.target}")
    if state.stop_reason:
        console.print(f"stop_reason={state.stop_reason}")
    console.print(f"confirmed={', '.join(state.final_report.confirmed_competitors)}")


@app.command()
def resume(
    run_id: str,
    provider: str | None = typer.Option(default=None, help="LLM provider name."),
    model: str | None = typer.Option(default=None, help="LLM model identifier."),
    base_url: str | None = typer.Option(default=None, help="Provider base URL."),
    api_key_env: str | None = typer.Option(default=None, help="Environment variable name for provider API key."),
    timeout_seconds: float | None = typer.Option(default=None, help="Provider request timeout in seconds."),
    max_retries: int | None = typer.Option(default=None, help="Provider request retry count."),
    runs_dir: Path | None = typer.Option(default=None, help="Override run artifact directory."),
) -> None:
    settings = _apply_settings_overrides(
        Settings(),
        provider=provider,
        model=model,
        base_url=base_url,
        api_key_env=api_key_env,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        runs_dir=runs_dir,
    )

    hydrate_runtime_secret(settings.api_key_env)
    controller = build_controller(settings)
    clear_cancel_request = getattr(getattr(controller, "store", None), "clear_cancel_request", None)
    if callable(clear_cancel_request):
        clear_cancel_request(run_id)
    state = controller.resume(run_id=run_id, budget=_default_budget())
    if state.final_report is None:
        draft = Synthesizer().run(state)
        state.final_report = CitationAgent().run(state, draft)
    _persist_final_artifacts(controller, state)

    console.print(f"run_id={state.run_id}")
    console.print(f"target={state.target}")
    if state.stop_reason:
        console.print(f"stop_reason={state.stop_reason}")
    console.print(f"confirmed={', '.join(state.final_report.confirmed_competitors)}")


@app.command()
def cancel(
    run_id: str,
    runs_dir: Path | None = typer.Option(default=None, help="Override run artifact directory."),
) -> None:
    settings = _apply_settings_overrides(Settings(), runs_dir=runs_dir)
    store = FileRunStore(settings.runs_dir)
    store.request_cancel(run_id, reason="cancelled by user")
    console.print(f"cancel_requested_for={run_id}")


@app.callback()
def main() -> None:
    """竞研台 CLI."""


if __name__ == "__main__":
    app()
