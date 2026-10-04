from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class Settings:
    db_path: Path
    llm_provider: Literal["mock", "deepseek"] = "mock"
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    request_timeout_seconds: float = 20.0
    max_upload_bytes: int = 1_048_576
    input_price_per_million: float = 0.30
    output_price_per_million: float = 1.20

    @classmethod
    def from_env(cls) -> "Settings":
        provider = os.getenv("LLM_PROVIDER", "mock").strip().lower()
        if provider not in {"mock", "deepseek"}:
            raise ValueError("LLM_PROVIDER must be 'mock' or 'deepseek'")
        return cls(
            db_path=Path(os.getenv("DB_PATH", "data/app.db")),
            llm_provider=provider,
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY") or None,
            deepseek_base_url=os.getenv(
                "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
            ).rstrip("/"),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
            request_timeout_seconds=float(
                os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "20")
            ),
        )
