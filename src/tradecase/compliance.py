"""Conservative, source-bound country and platform rule checks.

This is an evidence validation aid, not legal advice or a complete market-access
approval. Rules and source assertions remain reviewable human/Agent inputs.
"""
from __future__ import annotations

import ipaddress
import json
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from tradecase.models import (
    CaseInput,
    ComplianceCheck,
    ComplianceResult,
    Evidence,
    RuleSet,
    SellerContext,
    utc_timestamp,
)
from tradecase.util import digest, json_bytes, no_symlinks, utc_now

if TYPE_CHECKING:
    from tradecase.case_store import CaseStore

ENGINE_VERSION = "compliance-v1"
CONTEXT_FIELDS = {"target_country", "origin_country", "platform", "sales_channel"}


def _date(value):
    return datetime.fromisoformat(value)


def _known(value):
    return value is not None and value != "" and value not in ("unknown", "unverified")


def _same_value(actual, required):
    # bool is deliberately not coerced from strings or numbers.
    return type(actual) is type(required) and actual == required


def _reserved_source(url):
    host = (urlsplit(url).hostname or "").rstrip(".").lower()
    if host in {"localhost", "example.com", "example.org", "example.net"}:
        return True
    if any(host.endswith(suffix) for suffix in (".invalid", ".test", ".example", ".localhost", ".local")):
        return True
    if any(host.endswith("." + domain) for domain in ("example.com", "example.org", "example.net")):
        return True
    try:
        return not ipaddress.ip_address(host).is_global
    except ValueError:
        return False


def _source_gaps(rule, evidence, checked_at):
    gaps = []
    if not rule.source_url:
        gaps.append("source_url")
    if not rule.source_current:
        gaps.append("current_official_source_unconfirmed")
    if not rule.effective_date:
        gaps.append("effective_date")
    elif date.fromisoformat(rule.effective_date) > _date(checked_at).date():
        gaps.append("rule_not_yet_effective")
    if not rule.reviewed_at:
        gaps.append("reviewed_at")
    elif _date(rule.reviewed_at) > _date(checked_at):
        gaps.append("review_time_in_future")
    if not rule.valid_until:
        gaps.append("valid_until")
    elif _date(rule.valid_until) < _date(checked_at):
        gaps.append("rule_review_expired")
    if rule.source_url and not rule.is_synthetic and _reserved_source(rule.source_url):
        gaps.append("reserved_example_source")
    expected_type = "government" if rule.check_type == "country" else "platform_official"
    if not rule.source_evidence_ids:
        gaps.append("official_source_evidence")
    for eid in rule.source_evidence_ids:
        row = evidence.get(eid)
        if not row:
            gaps.append("missing_evidence:" + eid)
            continue
        if row.source_type != expected_type or row.assertion_status != "supported" or row.source_url != rule.source_url:
            gaps.append("unverified_official_evidence:" + eid)
        if row.is_synthetic != rule.is_synthetic:
            gaps.append("source_synthetic_mismatch:" + eid)
        if _date(row.captured_at) > _date(checked_at):
            gaps.append("source_capture_in_future:" + eid)
        if row.source_url and not row.is_synthetic and _reserved_source(row.source_url):
            gaps.append("reserved_evidence_source:" + eid)
    return sorted(set(gaps))


def _rule_check(rule, inquiry, seller, evidence, checked_at):
    missing_context, mismatches = [], []
    for key, expected in rule.applicability.items():
        actual = getattr(inquiry, key) if key in CONTEXT_FIELDS else seller.product_attributes.get(key)
        if not _known(actual):
            missing_context.append(key)
        elif not _same_value(actual, expected):
            mismatches.append(f"{key}={actual!r} differs from rule scope {expected!r}")
    missing_attributes = [key for key in rule.attributes_required if not _known(seller.product_attributes.get(key))]
    observed = [key for key in rule.attributes_required if _known(seller.product_attributes.get(key))]
    source_gaps = _source_gaps(rule, evidence, checked_at)
    unmet = [key for key, expected in rule.required_values.items()
             if key not in missing_attributes and not _same_value(seller.product_attributes.get(key), expected)]
    missing = []
    if missing_context:
        status, severity = "needs_context", rule.severity
        missing = sorted(missing_context)
        explanation = "Missing applicability context: " + ", ".join(missing)
    elif mismatches:
        status, severity = "not_applicable", "info"
        explanation = "Outside this rule's explicit scope: " + "; ".join(mismatches)
    elif missing_attributes:
        status, severity = "needs_context", rule.severity
        missing = sorted(missing_attributes)
        explanation = "Missing required product attributes: " + ", ".join(missing)
    elif source_gaps:
        status, severity = "needs_verification", rule.severity
        missing = source_gaps
        explanation = "Official current rule basis is incomplete: " + ", ".join(missing)
    elif unmet:
        status, severity = "fail", rule.severity
        explanation = "Observed values do not satisfy required values: " + ", ".join(sorted(unmet))
    else:
        status, severity = "pass", "info"
        explanation = "Declared attributes match this scoped, source-bound rule; not a complete legal or platform approval."
    return ComplianceCheck(
        check_id="check-" + rule.rule_id,
        check_type=rule.check_type,
        jurisdiction=rule.applicability.get("target_country") if rule.check_type == "country" else inquiry.target_country,
        platform=rule.applicability.get("platform") if rule.check_type == "platform" else inquiry.platform,
        product_scope=rule.product_scope,
        rule_id=rule.rule_id,
        rule_version=rule.version,
        effective_date=rule.effective_date,
        checked_at=checked_at,
        source_url=rule.source_url,
        required_attributes=list(rule.attributes_required),
        observed_attributes=observed,
        status=status,
        severity=severity,
        rationale=rule.rationale + " " + explanation,
        affected_content="seller_context.product_attributes",
        suggested_action=rule.suggested_action,
        evidence_ids=[eid for eid in rule.source_evidence_ids if eid in evidence],
        missing_items=missing,
        is_synthetic=rule.is_synthetic or inquiry.is_synthetic,
    )


def _missing_check(kind, inquiry, checked_at):
    context = inquiry.target_country if kind == "country" else inquiry.platform
    status = "needs_verification" if _known(context) else "needs_context"
    field = "target_country" if kind == "country" else "platform"
    return ComplianceCheck(
        check_id="check-missing-" + kind, check_type=kind,
        jurisdiction=inquiry.target_country, platform=inquiry.platform,
        product_scope=inquiry.product_summary or "Product scope unknown",
        rule_id="missing-" + kind, rule_version=ENGINE_VERSION, checked_at=checked_at,
        status=status, severity="high",
        rationale=(f"No rules cover the declared {field}." if _known(context) else f"Missing {field}; applicability unknown."),
        suggested_action=f"Provide {field} and research the current official rules for the actual product scope.",
        missing_items=["applicable_official_rule" if _known(context) else field], is_synthetic=inquiry.is_synthetic,
    )


def evaluate_compliance(case_input, seller_context, evidence, rules_snapshot, *, checked_at):
    """Pure deterministic evaluation at an explicitly recorded timestamp."""
    inquiry = CaseInput.model_validate(case_input)
    seller = SellerContext.model_validate(seller_context)
    rules = RuleSet.model_validate(rules_snapshot)
    timestamp = utc_timestamp(checked_at)
    rows = [Evidence.model_validate(row) for row in evidence]
    if len({row.evidence_id for row in rows}) != len(rows):
        raise ValueError("duplicate evidence_id")
    evidence_index = {row.evidence_id: row for row in rows}
    if not inquiry.is_synthetic and (seller.is_synthetic or any(row.is_synthetic for row in rows)
                                     or any(rule.is_synthetic for rule in rules.rules)):
        raise ValueError("synthetic rules or evidence cannot determine compliance for a real Case")
    checks = [_rule_check(rule, inquiry, seller, evidence_index, timestamp) for rule in rules.rules]
    for kind, field in [("country", "target_country"), ("platform", "platform")]:
        relevant = [rule for rule in rules.rules if rule.check_type == kind]
        context = getattr(inquiry, field)
        if not relevant or (_known(context) and not any(
            _same_value(rule.applicability[field], context) for rule in relevant
        )):
            checks.append(_missing_check(kind, inquiry, timestamp))
    return ComplianceResult(
        case_id=inquiry.case_id, checks=checks, is_synthetic=inquiry.is_synthetic,
        checked_at=timestamp, rule_engine_version=ENGINE_VERSION,
        rules_snapshot_ref="rules_snapshot.json", rules_snapshot_sha256=digest(json_bytes(rules)),
    ).model_dump(mode="json")


def check_case(store: CaseStore, rules_path: str | Path, checked_at: str | None = None) -> dict:
    """Persist the evaluated rules and checks. Real Cases always use the current clock."""
    path = Path(rules_path).absolute()
    no_symlinks(path)
    raw_rules = path.read_bytes()
    rules = RuleSet.model_validate(json.loads(raw_rules))
    inquiry = store.read("input.json")
    if checked_at is not None and (not inquiry.get("is_synthetic") or any(not rule.is_synthetic for rule in rules.rules)):
        raise ValueError("checked_at override is permitted only for a synthetic Case with all-synthetic rules")
    timestamp = checked_at if checked_at is not None else utc_now()
    evidence = store.read("evidence.jsonl") if (store.path / "evidence.jsonl").exists() else []
    result = evaluate_compliance(inquiry, store.read("seller_context.json"), evidence, rules.model_dump(mode="json"),
                                 checked_at=timestamp)
    if store.read("manifest.json")["state"] in {"completed", "cancelled"}:
        raise ValueError("final Case requires explicit reopen before compliance evaluation")
    store.transition("running", "compliance")
    store.write("rules_snapshot.json", rules)
    store.write("compliance.json", result)
    store.record("compliance_evaluated", {"checked_at": timestamp, "rule_engine_version": ENGINE_VERSION,
                 "rules_input_sha256": digest(raw_rules), "rules_snapshot_sha256": result["rules_snapshot_sha256"]})
    unresolved = [f"{row['check_id']}:{row['status']}" for row in result["checks"]
                  if row["status"] not in {"pass", "not_applicable"}]
    if unresolved:
        store.transition("needs_review", "compliance", blockers=unresolved)
    return result
