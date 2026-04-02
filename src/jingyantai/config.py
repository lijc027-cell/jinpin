from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    model_provider: str = "anthropic"
    model_name: str = "claude-3-7-sonnet-latest"
    tavily_api_key: str = ""
    github_token: str = ""
    runs_dir: Path = Path("./runs")
