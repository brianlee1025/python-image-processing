from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import SettingsConfigDict

from .db import DatabaseSettings
from .kafka import KafkaSettings
from .render import RenderSettings


class Settings(DatabaseSettings, KafkaSettings, RenderSettings):
    """Every setting, from the environment or from a `.env` next to the repo.

    The `.env` is for local development only - it is read relative to the
    working directory, and real environments pass proper environment variables.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    project_name: str = "image-processing-service"
    debug: bool = False
    environment: Literal["development", "test", "production"] = "development"

    # The HTTP API is a development/fallback surface. Production callers must
    # authenticate, and request admission happens before FastAPI parses JSON so
    # an oversized base64 payload cannot consume unbounded memory.
    http_api_key: SecretStr | None = None
    http_max_request_bytes: int = Field(default=12_000_000, ge=1024, le=100_000_000)
    http_rate_limit_per_minute: int = Field(default=120, ge=1, le=100_000)
    worker_heartbeat_file: Path | None = None

    @property
    def is_production(self) -> bool:
        return self.environment == "production"
