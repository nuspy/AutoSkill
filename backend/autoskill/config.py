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
    public_url: str = "http://localhost:8100"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]
    # The browser extension this server pairs with. It goes into the setup script, which registers the
    # native messaging host to accept that id and no other — so an operator running their own AutoSkill
    # with their own build of the extension sets this, and the two halves still match.
    extension_id: str = "cnkodldlkekifpmakgkkmpdikbobbjff"

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

    # llmswitch: the LLM providers of the machine this server runs on (see autoskill/llm/switch.py).
    # The registry file holds API keys, so it lives outside the repository: leave the path empty to
    # use the library default (%LOCALAPPDATA%/autoskill or ~/.config/autoskill).
    llmswitch_enabled: bool = True
    llmswitch_registry: Path | None = None
    # Local engines only: True lets a request load the chosen model when the GPU is idle, False
    # limits the VRAM rule to using what is already in memory.
    llmswitch_load_models: bool = True
    # How long to wait for one completion. A local reasoning model writes thousands of tokens before
    # the answer at tens of tokens per second, so this is generous — but not 15 minutes: at 900s a
    # single hung or runaway generation (a reasoning model with no token cap can loop and generate
    # without end) stalled a whole interview step for the full quarter hour before the retry, which
    # then answered in seconds. Paired with a token cap (llm_output_limit_*), a real call finishes
    # well inside this and a stuck one is abandoned in minutes, not a quarter of an hour.
    llm_request_timeout_seconds: float = 240.0
    # Local reasoning models write a chain of thought before the answer, and left unbounded they fill
    # the whole token cap with it: a single constrained-JSON call was measured generating ~5,500
    # tokens (36s at 150 tok/s). `chat_template_kwargs.thinking_budget` asks the engine to cap that
    # reasoning, and it goes only to local engines (an OpenAI/Gemini endpoint rejects the key); 0
    # disables it. Best-effort, not a guarantee: some builds honour it, but qwen3.5-a3b in LM Studio
    # ignores it under structured output (measured). The reliable per-turn win is calling the model
    # fewer times — see the conditional supervisor in services/procedures/defs/interview.py.
    llm_thinking_budget: int = 512

    @property
    def dist_dir(self) -> Path:
        return self.local_dist_dir or (self.data_dir / "dist")

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
