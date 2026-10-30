"""Rules first; semantic candidates require exact inquiry quotations and schema gates."""

import re
from typing import Literal

from pydantic import Field

from tradecase.platform.contracts import Input

from .schemas import Intent


class Opportunity(Input):
    intent: Intent
    status: Literal["suggested", "needs_input", "not_recommended"] = "suggested"
    reason: str = Field(max_length=1000)
    requirement_quote: str = Field(min_length=1, max_length=1000)
    strategy: Literal["generate", "reuse/compose", "compose/edit"]
    missing_inputs: list[str] = Field(default_factory=list)
    priority: int = Field(ge=0, le=100)


RULES = [
    ("odm_concept", r"\bODM\b|new (?:structure|design|shape)|新结构|新造型", "generate", 95),
    ("oem_preview", r"\bOEM\b|\blogo\b|custom colou?r|定制|木纹", "compose/edit", 90),
    ("packaging_preview", r"custom packag|packaging (?:preview|design)|彩盒|包装设计", "compose/edit", 85),
    ("product_comparison", r"compar|multiple SKU|多个(?:产品|型号)|对比", "reuse/compose", 80),
    (
        "spec_illustration",
        r"(?:dimension|structure|configuration).*(?:diagram|illustrat)|结构图|尺寸图",
        "reuse/compose",
        75,
    ),
    ("buyer_presentation", r"visual (?:proposal|presentation)|视觉提案", "reuse/compose", 70),
]


def detect(text, semantic_candidates=None):
    results = []
    for intent, pattern, strategy, priority in RULES:
        match = re.search(pattern, text, re.I)
        if match:
            results.append(
                Opportunity(
                    intent=intent,
                    reason="Buyer inquiry includes a visual requirement; no generation is authorized.",
                    requirement_quote=text[max(0, match.start() - 50) : match.end() + 100],
                    strategy=strategy,
                    priority=priority,
                    missing_inputs=["Product facts", "Authorized reference assets", "Human plan approval"],
                ).model_dump()
            )
    for candidate in semantic_candidates or []:
        item = Opportunity.model_validate(candidate)
        if item.requirement_quote not in text:
            continue
        if item.intent not in {r["intent"] for r in results}:
            results.append(item.model_dump())
    return sorted(results, key=lambda x: -x["priority"])[:3]
