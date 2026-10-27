"""One bounded P4 security review: provenance, scope and replay integrity."""

import copy
import json
from pathlib import Path

import pytest

from tradecase.case_store import CaseStore
from tradecase.compliance import check_case, evaluate_compliance
from tradecase.validation import validate_case

STAMP = "2026-10-27T12:00:00Z"
ROOT = Path(__file__).parents[2]


def review_inputs():
    inquiry = {"case_id": "review-compliance", "received_at": STAMP, "buyer_message": "Synthetic inquiry",
               "target_country": "US", "platform": "amazon_us", "is_synthetic": True}
    seller = {"is_synthetic": True, "product_attributes": {
        "children_product": True, "tracking_label_present": True, "listing_safety_reviewed": True,
    }}
    rules = json.loads((ROOT / "rules/synthetic-demo-v1.json").read_text())
    evidence = [{"evidence_id": rule["source_evidence_ids"][0], "claim": "Synthetic rule", "excerpt": "Synthetic rule",
                 "source_url": rule["source_url"], "source_type": "government" if rule["check_type"] == "country"
                 else "platform_official", "captured_at": STAMP, "retrieved_by": "offline_review",
                 "assertion_status": "supported", "is_synthetic": True} for rule in rules["rules"]]
    return inquiry, seller, evidence, rules


def test_missing_product_class_never_passes_country_rule():
    args = review_inputs()
    del args[1]["product_attributes"]["children_product"]
    checks = evaluate_compliance(*args, checked_at=STAMP)["checks"]
    assert checks[0]["status"] == "needs_context"
    assert "children_product" in checks[0]["missing_items"]


def test_future_effective_date_cannot_hide_behind_iso_week_timestamp():
    args = review_inputs()
    args[3]["rules"][0]["effective_date"] = "2026-11-01"
    # ISO week 44 Tuesday is 2026-10-27. UTC ISO 8601 week dates are accepted by
    # the public timestamp contract and must have the same date semantics.
    checks = evaluate_compliance(*args, checked_at="2026-W44-2T12:00:00Z")["checks"]
    assert checks[0]["status"] == "needs_verification"
    assert "rule_not_yet_effective" in checks[0]["missing_items"]


def test_observed_attributes_cannot_be_rewritten_after_a_valid_check(tmp_path):
    inquiry, seller, evidence, rules = review_inputs()
    store = CaseStore.create(tmp_path / "case", inquiry, seller)
    store.write("evidence.jsonl", evidence)
    source = tmp_path / "rules.json"
    source.write_text(json.dumps(rules))
    result = check_case(store, source, checked_at=STAMP)
    assert validate_case(store.path) == []
    result["checks"][0]["observed_attributes"].append("unreviewed_attribute")
    store.write("compliance.json", result)
    assert any("recomputed" in error for error in validate_case(store.path))


def test_rule_evidence_reference_gap_remains_visible_and_not_a_pass():
    args = review_inputs()
    args[3]["rules"][0]["source_evidence_ids"] = ["missing-rule-evidence"]
    check = evaluate_compliance(*args, checked_at=STAMP)["checks"][0]
    assert check["status"] == "needs_verification"
    assert check["evidence_ids"] == []
    assert "missing_evidence:missing-rule-evidence" in check["missing_items"]


def test_false_scope_is_not_missing_and_empty_rules_never_pass():
    args = review_inputs()
    args[1]["product_attributes"]["children_product"] = False
    check = evaluate_compliance(*args, checked_at=STAMP)["checks"][0]
    assert check["status"] == "not_applicable"
    assert "children_product=False" in check["rationale"]
    args[3]["rules"] = []
    checks = evaluate_compliance(*args, checked_at=STAMP)["checks"]
    assert len(checks) == 2
    assert all(row["status"] == "needs_verification" for row in checks)


def test_real_case_rejects_synthetic_source_even_if_rule_is_marked_real():
    inquiry, seller, evidence, rules = review_inputs()
    inquiry["is_synthetic"] = seller["is_synthetic"] = False
    for rule in rules["rules"]:
        rule["is_synthetic"] = False
    before = copy.deepcopy(evidence)
    with pytest.raises(ValueError, match="synthetic"):
        evaluate_compliance(inquiry, seller, evidence, rules, checked_at=STAMP)
    assert evidence == before
