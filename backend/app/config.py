"""Runtime configuration. Everything comes from environment variables (or a local, gitignored .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
# Local dev convenience only; on Vercel the variables come from the project settings.
load_dotenv(REPO_ROOT / ".env", override=False)

# Prompts live in orchestration/prompts.py; policy text in backend/steering/*.md.


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""), repr=False)
    live_model: str = field(default_factory=lambda: os.getenv("GEMINI_LIVE_MODEL", "gemini-3.8-live"))
    vision_model: str = field(default_factory=lambda: os.getenv("GEMINI_VISION_MODEL", "gemini-3.8-flash"))
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./data/labmate.db"))
    turso_url: str = field(default_factory=lambda: os.getenv("TURSO_DATABASE_URL", ""))
    turso_token: str = field(default_factory=lambda: os.getenv("TURSO_AUTH_TOKEN", ""), repr=False)
    vision_provider: str = field(default_factory=lambda: os.getenv("VISION_PROVIDER", "gemini"))
    modal_enabled: bool = field(default_factory=lambda: os.getenv("MODAL_ENABLED", "false").lower() == "true")
    modal_app: str = field(default_factory=lambda: os.getenv("MODAL_VISION_APP", "labmate-vision"))
    modal_function: str = field(default_factory=lambda: os.getenv("MODAL_VISION_FUNCTION", "detect"))
    # A recording whose client has not sent a heartbeat for this long is expired server-side.
    heartbeat_timeout_s: int = field(default_factory=lambda: int(os.getenv("RECORDING_HEARTBEAT_TIMEOUT_S", "45")))
    max_image_bytes: int = 4 * 1024 * 1024  # Vercel request bodies are capped at 4.5 MB
    vercel_env: str = field(default_factory=lambda: os.getenv("VERCEL_ENV", ""))
    allow_production: bool = field(default_factory=lambda: os.getenv("ALLOW_PRODUCTION", "") == "1")

    @property
    def database_label(self) -> str:
        """Human-readable DB location for diagnostics (never includes tokens)."""
        if self.turso_url:
            return "turso:" + self.turso_url.split("://", 1)[-1]
        return str(self.sqlite_path)

    @property
    def sqlite_path(self) -> Path:
        raw = self.database_url.removeprefix("sqlite:///")
        p = Path(raw)
        return p if p.is_absolute() else (REPO_ROOT / p).resolve()


def get_settings() -> Settings:
    return Settings()
