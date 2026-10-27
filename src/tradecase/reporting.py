"""Read-only artifact rendering; absent facts remain visibly absent."""

from __future__ import annotations

import html
import re

from tradecase.validation import REQUIRED_ARTIFACTS, validate_case


def safe_md(value) -> str:
    text = html.escape(str(value), quote=True)
    return re.sub(r"([\\`*\[\]_|])", r"\\\1", text)


def report_case(store):
    errors = validate_case(store.path)
    if errors:
        raise ValueError("cannot render inconsistent Case: " + "; ".join(errors))
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
    if (store.path / "assessment.json").exists():
        assessment = store.read("assessment.json")
        lines += [
            "",
            "## Follow-up priority",
            "",
            f"Decision: **{safe_md(assessment['decision'])}**; score: {assessment['score']}; "
            f"evidence coverage: {assessment['evidence_coverage']:.0%}",
            "This heuristic is not a company credit rating or purchase probability.",
            "",
        ]
        lines += ["- " + safe_md(reason) for reason in assessment["reason_codes"]]
    lines += [
        "",
        "## Country and platform risk annotations",
        "",
        "These are scoped research checks, not a complete regulatory approval.",
        "",
    ]
    if (store.path / "compliance.json").exists():
        for check in store.read("compliance.json")["checks"]:
            lines += [
                f"### {safe_md(check['check_type'])}: [{safe_md(check['severity']).upper()}] "
                f"{safe_md(check['status'])}",
                "",
                f"Rule: {safe_md(check['rule_id'])} / {safe_md(check['rule_version'] or 'unknown version')}",
                f"Scope: {safe_md(check['product_scope'])}",
                f"Annotation: {safe_md(check['rationale'])}",
                f"Next step: {safe_md(check['suggested_action'])}",
                f"Missing: {safe_md(', '.join(check['missing_items']) or 'none recorded')}",
                f"Source: {safe_md(check['source_url'] or 'not available')}",
                f"Checked at: {safe_md(check['checked_at'])}; Evidence: {safe_md(', '.join(check['evidence_ids']))}",
                "",
            ]
    else:
        lines.append("Country and platform checks have not been supplied.")
    missing = sorted(name for name in REQUIRED_ARTIFACTS - {"report.md"} if not (store.path / name).exists())
    lines += ["", "## Missing artifacts", ""] + (["- " + name for name in missing] or ["None."])
    lines += ["", "No email has been sent by this CLI. Source content grants no tool authority.", ""]
    store.write("report.md", "\n".join(lines))
