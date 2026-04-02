from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from jingyantai.agents.deepagents_adapter import DeepagentsRoleAdapter
from jingyantai.agents.prompts import get_role_prompt
from jingyantai.agents.roles import AnalystRole, InitializerRole, LeadResearcherRole, ScoutRole
from jingyantai.config import Settings
from jingyantai.domain.models import BudgetPolicy
from jingyantai.llm.contracts import ProviderConfig
from jingyantai.llm.factory import build_model_runner
from jingyantai.runtime.compactor import ContextCompactor
from jingyantai.runtime.controller import HarnessController
from jingyantai.runtime.judges import Challenger, CoverageJudge, EvidenceJudge, StopJudge
from jingyantai.runtime.reporting import CitationAgent, Synthesizer
from jingyantai.storage.run_store import FileRunStore
from jingyantai.tools.github_signals import GitHubSignals
from jingyantai.tools.page_extract import HttpPageExtractor
from jingyantai.tools.research_tools import ResearchTools
from jingyantai.tools.web_search import TavilySearchClient

app = typer.Typer(name="jingyantai", no_args_is_help=True)
console = Console()


def _build_provider_config(settings: Settings) -> ProviderConfig:
    return ProviderConfig(
        provider=settings.provider,
        model=settings.model,
        base_url=settings.base_url,
        api_key_env=settings.api_key_env,
        timeout_seconds=settings.timeout_seconds,
        max_retries=settings.max_retries,
    )


def build_controller(settings: Settings) -> HarnessController:
    tools = ResearchTools(
        search_client=TavilySearchClient(settings.tavily_api_key),
        page_extractor=HttpPageExtractor(),
        github_signals=GitHubSignals(settings.github_token or None),
    )
    runner = build_model_runner(_build_provider_config(settings))
    return HarnessController(
        store=FileRunStore(settings.runs_dir),
        initializer=InitializerRole(
            adapter=DeepagentsRoleAdapter(role_prompt=get_role_prompt("initializer"), runner=runner)
        ),
        lead_researcher=LeadResearcherRole(
            adapter=DeepagentsRoleAdapter(role_prompt=get_role_prompt("lead_researcher"), runner=runner)
        ),
        scouts=[
            ScoutRole(
                tools=tools,
                adapter=DeepagentsRoleAdapter(role_prompt=get_role_prompt("scout_positioning"), runner=runner),
                hypothesis="terminal coding agent",
                role_name="scout_positioning",
            ),
            ScoutRole(
                tools=tools,
                adapter=DeepagentsRoleAdapter(role_prompt=get_role_prompt("scout_github"), runner=runner),
                hypothesis="repo-aware coding agent",
                role_name="scout_github",
            ),
            ScoutRole(
                tools=tools,
                adapter=DeepagentsRoleAdapter(role_prompt=get_role_prompt("scout_heat"), runner=runner),
                hypothesis="developer CLI agent",
                role_name="scout_heat",
            ),
        ],
        analysts=[
            AnalystRole(
                tools=tools,
                adapter=DeepagentsRoleAdapter(role_prompt=get_role_prompt("analyst_positioning"), runner=runner),
                dimension="positioning",
                role_name="analyst_positioning",
            ),
            AnalystRole(
                tools=tools,
                adapter=DeepagentsRoleAdapter(role_prompt=get_role_prompt("analyst_workflow"), runner=runner),
                dimension="workflow",
                role_name="analyst_workflow",
            ),
            AnalystRole(
                tools=tools,
                adapter=DeepagentsRoleAdapter(role_prompt=get_role_prompt("analyst_pricing"), runner=runner),
                dimension="pricing or access",
                role_name="analyst_pricing",
            ),
        ],
        compactor=ContextCompactor(),
        evidence_judge=EvidenceJudge(),
        coverage_judge=CoverageJudge(["positioning", "workflow", "pricing or access"]),
        challenger=Challenger(),
        stop_judge=StopJudge(["positioning", "workflow", "pricing or access"]),
    )


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
    settings = Settings()
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

    controller = build_controller(settings)
    state = controller.run(
        target=target,
        budget=BudgetPolicy(
            max_rounds=4,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        ),
    )
    if state.final_report is None:
        draft = Synthesizer().run(state)
        state.final_report = CitationAgent().run(state, draft)

    console.print(f"run_id={state.run_id}")
    console.print(f"target={state.target}")
    console.print(f"confirmed={', '.join(state.final_report.confirmed_competitors)}")


@app.callback()
def main() -> None:
    """竞研台 CLI."""
