"""Application settings (environment driven)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTOSKILL_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    secret_key: str = Field(default="change-me-in-production-please-32-bytes")
    database_url: str = "sqlite+aiosqlite:///./autoskill.db"
    redis_url: str = "redis://localhost:6379/0"
    jobs: Literal["inline", "arq"] = "inline"
    events: Literal["memory", "redis"] = "memory"
    data_dir: Path = Path("./data")
    public_url: str = "http://localhost:8000"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    access_token_minutes: int = 15
    refresh_token_days: int = 30
    device_code_minutes: int = 15
    cookie_secure: bool = False

    registration_open: bool = True
    log_level: str = "INFO"

    # outgoing email: console (log + in-memory outbox, default for dev/tests), smtp, none
    email_backend: Literal["console", "smtp", "none"] = "console"
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True
    email_from: str = "AutoSkill <no-reply@localhost>"

    # install bundles (/dl/...): default lifetime of a version download link, max artifact upload size
    download_link_days: int = 30
    library_artifact_max_mb: int = 64
    # where built wheels of autoskill-local are served from (deploy/install.sh fills it); default data_dir/dist
    local_dist_dir: Path | None = None

    @property
    def dist_dir(self) -> Path:
        return self.local_dist_dir or (self.data_dir / "dist")

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
