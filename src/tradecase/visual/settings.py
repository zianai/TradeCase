"""Visual execution is an independent opt-in; approvals cannot disable gates."""

import os
from dataclasses import dataclass, field


@dataclass
class VisualSettings:
    enabled: bool = field(default_factory=lambda: os.getenv("TRADECASE_VISUAL_ENABLED") == "true")
    max_budget_usd: float = field(default_factory=lambda: float(os.getenv("TRADECASE_VISUAL_MAX_BUDGET_USD", "5")))
    max_variants: int = 8
    sync_interval: int = 15
    max_asset_bytes: int = 2 * 1024 * 1024
    provider: str = field(default_factory=lambda: os.getenv("TRADECASE_VISUAL_PROVIDER", "mock"))
    paid_enabled: bool = field(default_factory=lambda: os.getenv("TRADECASE_VISUAL_PAID_ENABLED") == "true")

    def __post_init__(self):
        import math

        if not math.isfinite(self.max_budget_usd) or not 0 <= self.max_budget_usd <= 100:
            raise ValueError("Invalid visual budget limit")
