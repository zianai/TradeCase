"""Explicit deployment switches. Defaults cannot send or invoke paid models."""

import math
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    database_url: str = field(
        default_factory=lambda: os.getenv("TRADECASE_DATABASE_URL", "sqlite:///.tradecase/platform.db")
    )
    storage_root: Path = field(
        default_factory=lambda: Path(os.getenv("TRADECASE_STORAGE_ROOT", ".tradecase/objects")).absolute()
    )
    work_root: Path = field(
        default_factory=lambda: Path(os.getenv("TRADECASE_WORK_ROOT", ".tradecase/work")).absolute()
    )
    storage_backend: str = field(default_factory=lambda: os.getenv("TRADECASE_STORAGE_BACKEND", "local"))
    s3_bucket: str = field(default_factory=lambda: os.getenv("TRADECASE_S3_BUCKET", ""))
    s3_endpoint_url: str = field(default_factory=lambda: os.getenv("TRADECASE_S3_ENDPOINT_URL", ""))
    s3_encryption: str = field(default_factory=lambda: os.getenv("TRADECASE_S3_ENCRYPTION", "AES256"))
    checkpoint_url: str = field(
        default_factory=lambda: os.getenv("TRADECASE_CHECKPOINT_URL", "sqlite:///.tradecase/checkpoints.sqlite")
    )
    redis_url: str = field(default_factory=lambda: os.getenv("TRADECASE_REDIS_URL", "redis://localhost:6379/0"))
    runtime: str = field(default_factory=lambda: os.getenv("TRADECASE_RUNTIME", "fake"))
    queue_mode: str = field(default_factory=lambda: os.getenv("TRADECASE_QUEUE_MODE", "local"))
    live_model_enabled: bool = field(default_factory=lambda: os.getenv("TRADECASE_LIVE_MODEL_ENABLED") == "true")
    outbound_enabled: bool = field(default_factory=lambda: os.getenv("TRADECASE_OUTBOUND_ENABLED") == "true")
    mail_connector: str = field(default_factory=lambda: os.getenv("TRADECASE_MAIL_CONNECTOR", "disabled"))
    demo_enabled: bool = field(default_factory=lambda: os.getenv("TRADECASE_DEMO_ENABLED") == "true")
    model: str = field(default_factory=lambda: os.getenv("TRADECASE_MODEL", ""))
    skills_root: Path = field(default_factory=lambda: Path(os.getenv("TRADECASE_SKILLS_ROOT", "skills")).absolute())
    public_fetch_enabled: bool = field(default_factory=lambda: os.getenv("TRADECASE_PUBLIC_FETCH_ENABLED") == "true")
    research_domains: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            value.strip().lower() for value in os.getenv("TRADECASE_RESEARCH_DOMAINS", "").split(",") if value.strip()
        )
    )
    max_case_cost_usd: float = field(default_factory=lambda: float(os.getenv("TRADECASE_MAX_CASE_COST_USD", "0.10")))
    usd_per_token_upper_bound: float | None = field(
        default_factory=lambda: (
            float(os.environ["TRADECASE_USD_PER_TOKEN_UPPER_BOUND"])
            if os.getenv("TRADECASE_USD_PER_TOKEN_UPPER_BOUND")
            else None
        )
    )
    max_model_turns: int = 4
    max_tool_calls: int = 8
    max_research_tokens: int = 24000
    max_research_rounds: int = 1
    max_upload_bytes: int = 2 * 1024 * 1024
    lease_seconds: int = 180
    max_case_seconds: int = 150

    def prepare(self):
        if self.runtime not in {"fake", "openai"}:
            raise ValueError("unsupported research runtime")
        if (
            not math.isfinite(self.max_case_cost_usd)
            or not 0 <= self.max_case_cost_usd <= 100
            or self.usd_per_token_upper_bound is not None
            and (not math.isfinite(self.usd_per_token_upper_bound) or self.usd_per_token_upper_bound <= 0)
        ):
            raise ValueError("model budget/pricing must be finite nonnegative limits")
        if not 0 <= self.max_research_rounds <= 3 or not 1 <= self.max_case_seconds <= 300:
            raise ValueError("invalid research round or wall-time bound")
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.work_root.mkdir(parents=True, exist_ok=True)
        if not self.checkpoint_url.startswith("postgres"):
            Path(self.checkpoint_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
