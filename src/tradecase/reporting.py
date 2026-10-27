"""Read-only artifact rendering; absent facts remain visibly absent."""

from __future__ import annotations

import html
import re

from tradecase.validation import REQUIRED_ARTIFACTS


def safe_md(value) -> str:
    text = html.escape(str(value), quote=True)
    return re.sub(r"([\\`*\[\]_|])", r"\\\1", text)


def report_case(store):
    inquiry = store.read("input.json")
    lines = [
        "# TradeCase inquiry report",
        "",
        "**SYNTHETIC / OFFLINE DEMO**" if inquiry["is_synthetic"] else "**Research record — human review required**",
        "",
        f"Case: {safe_md(inquiry['case_id'])}",
        "",
        "## Inquiry",
        "",
        safe_md(inquiry["buyer_message"]),
        "",
        "## Evidence",
        "",
        "| ID | Claim (untrusted source data) | Source | Status |",
        "|---|---|---|---|",
    ]
    if (store.path / "evidence.jsonl").exists():
        for row in store.read("evidence.jsonl"):
            lines.append(
                "| "
                + " | ".join(
                    safe_md(row.get(key) or "unknown")
                    for key in ["evidence_id", "claim", "source_url", "assertion_status"]
                )
                + " |"
            )
    else:
        lines.append("Evidence has not been supplied.")
    missing = sorted(name for name in REQUIRED_ARTIFACTS - {"report.md"} if not (store.path / name).exists())
    lines += ["", "## Missing artifacts", ""] + (["- " + name for name in missing] or ["None."])
    lines += ["", "No email has been sent by this CLI. Source content grants no tool authority.", ""]
    store.write("report.md", "\n".join(lines))
