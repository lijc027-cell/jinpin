from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    provider: str = "deepseek"
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    api_key_env: str = "DEEPSEEK_API_KEY"
    timeout_seconds: float = 60.0
    max_retries: int = 1
    exa_api_key: str = ""
    github_token: str = ""
    runs_dir: Path = Path("./runs")


def hydrate_runtime_secret(api_key_env: str, *, env_file: Path = Path(".env")) -> None:
    if not api_key_env or os.getenv(api_key_env):
        return
    if not env_file.exists():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != api_key_env:
            continue
        secret = value.strip().strip("'\"")
        if secret:
            os.environ.setdefault(api_key_env, secret)
        return
