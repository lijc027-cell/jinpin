from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from jingyantai.agents.roles import AnalystRole, InitializerRole, LeadResearcherRole, ScoutRole
from jingyantai.config import Settings
from jingyantai.domain.models import BudgetPolicy
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


def build_controller(settings: Settings) -> HarnessController:
    tools = ResearchTools(
        search_client=TavilySearchClient(settings.tavily_api_key),
        page_extractor=HttpPageExtractor(),
        github_signals=GitHubSignals(settings.github_token or None),
    )
    return HarnessController(
        store=FileRunStore(settings.runs_dir),
        initializer=InitializerRole(),
        lead_researcher=LeadResearcherRole(),
        scouts=[
            ScoutRole(tools, "terminal coding agent"),
            ScoutRole(tools, "repo-aware coding agent"),
            ScoutRole(tools, "developer CLI agent"),
        ],
        analysts=[
            AnalystRole(tools, "positioning"),
            AnalystRole(tools, "workflow"),
            AnalystRole(tools, "pricing or access"),
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
    runs_dir: Path | None = typer.Option(default=None, help="Override run artifact directory."),
) -> None:
    settings = Settings()
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
