"""Rule provenance, applicability, strict values and reproducible Case checks."""

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from tradecase.case_store import CaseStore
from tradecase.compliance import check_case, evaluate_compliance
from tradecase.models import Rule, RuleSet
from tradecase.validation import validate_case

STAMP = "2026-10-27T12:00:00Z"
ROOT = Path(__file__).parents[2]


def inputs():
    inquiry = dict(case_id="compliance-test", received_at=STAMP, buyer_message="Synthetic inquiry",
                   target_country="US", platform="amazon_us", is_synthetic=True)
    seller = dict(is_synthetic=True, product_attributes={
        "children_product": True, "tracking_label_present": True, "listing_safety_reviewed": True,
    })
    rules = json.loads((ROOT / "rules/synthetic-demo-v1.json").read_text())
    evidence = [dict(
        evidence_id=rule["source_evidence_ids"][0], claim="Synthetic demonstration policy", excerpt="Synthetic rule text",
        source_url=rule["source_url"], source_type="government" if rule["check_type"] == "country" else "platform_official",
        captured_at=STAMP, retrieved_by="offline_fixture", assertion_status="supported", is_synthetic=True,
    ) for rule in rules["rules"]]
    return inquiry, seller, evidence, rules


def evaluate(*, change=None):
    args = inputs()
    if change:
        change(*args)
    return evaluate_compliance(*args, checked_at=STAMP)


def test_both_synthetic_checks_pass_and_repeat_identically():
    args = inputs()
    before = copy.deepcopy(args)
    first = evaluate_compliance(*args, checked_at=STAMP)
    second = evaluate_compliance(*args, checked_at=STAMP)
    assert first == second
    assert args == before
    assert {row["check_type"] for row in first["checks"]} == {"country", "platform"}
    assert {row["status"] for row in first["checks"]} == {"pass"}
    assert first["is_synthetic"] is True
    assert len(first["rules_snapshot_sha256"]) == 64


@pytest.mark.parametrize("field", ["source_url", "effective_date", "reviewed_at", "valid_until"])
def test_unconfirmed_rule_provenance_never_passes(field):
    result = evaluate(change=lambda i, s, e, r: r["rules"][0].update({field: None}))
    assert result["checks"][0]["status"] == "needs_verification"


@pytest.mark.parametrize("mutation", [
    lambda i, s, e, r: r["rules"][0].update(source_current=False),
    lambda i, s, e, r: r["rules"][0].update(source_current=None),
    lambda i, s, e, r: r["rules"][0].update(valid_until="2026-10-26T23:00:00Z"),
    lambda i, s, e, r: r["rules"][0].update(effective_date="2027-01-01"),
    lambda i, s, e, r: r["rules"][0].update(reviewed_at="2027-01-01T00:00:00Z"),
    lambda i, s, e, r: e[0].update(source_type="search_snippet"),
    lambda i, s, e, r: e[0].update(assertion_status="unverified"),
    lambda i, s, e, r: e[0].update(source_url="https://different.invalid"),
    lambda i, s, e, r: e[0].update(captured_at="2027-01-01T00:00:00Z"),
    lambda i, s, e, r: r["rules"][0].update(source_evidence_ids=["not-present"]),
])
def test_missing_current_official_evidence_never_passes(mutation):
    result = evaluate(change=mutation)
    assert result["checks"][0]["status"] == "needs_verification"
    assert result["checks"][0]["missing_items"]


def test_missing_product_attribute_is_context_not_a_pass():
    result = evaluate(change=lambda i, s, e, r: s["product_attributes"].pop("tracking_label_present"))
    assert result["checks"][0]["status"] == "needs_context"
    assert "tracking_label_present" in result["checks"][0]["missing_items"]


def test_false_is_observed_and_fails_required_true():
    result = evaluate(change=lambda i, s, e, r: s["product_attributes"].update(tracking_label_present=False))
    check = result["checks"][0]
    assert check["status"] == "fail"
    assert "tracking_label_present" in check["observed_attributes"]
    assert "tracking_label_present" not in check["missing_items"]


def test_string_true_does_not_equal_boolean_true():
    result = evaluate(change=lambda i, s, e, r: s["product_attributes"].update(tracking_label_present="true"))
    assert result["checks"][0]["status"] == "fail"


def test_false_can_be_a_required_value():
    def change(i, s, e, r):
        s["product_attributes"]["tracking_label_present"] = False
        r["rules"][0]["required_values"]["tracking_label_present"] = False
    assert evaluate(change=change)["checks"][0]["status"] == "pass"


def test_missing_platform_and_country_get_explicit_context_checks():
    result = evaluate(change=lambda i, s, e, r: i.update(target_country=None, platform=None))
    assert len(result["checks"]) == 2
    assert {row["status"] for row in result["checks"]} == {"needs_context"}


def test_product_scope_mismatch_is_explained_not_applicable():
    result = evaluate(change=lambda i, s, e, r: s["product_attributes"].update(children_product=False))
    assert result["checks"][0]["status"] == "not_applicable"
    assert "children_product" in result["checks"][0]["rationale"]


def test_wrong_country_does_not_silently_claim_coverage():
    result = evaluate(change=lambda i, s, e, r: i.update(target_country="CA"))
    assert any(row["check_type"] == "country" and row["status"] == "needs_verification" for row in result["checks"])


def test_empty_rules_produce_review_checks_never_vacuous_pass():
    result = evaluate(change=lambda i, s, e, r: r.update(rules=[]))
    assert len(result["checks"]) == 2
    assert {row["status"] for row in result["checks"]} == {"needs_verification"}


@pytest.mark.parametrize("mutation", [
    lambda rule: rule.update(attributes_required=[]),
    lambda rule: rule.update(required_values={}),
    lambda rule: rule.update(required_values={"undeclared": True}),
    lambda rule: rule.update(applicability={}),
])
def test_rule_cannot_be_empty_or_vacuous(mutation):
    rule = inputs()[-1]["rules"][0]
    mutation(rule)
    with pytest.raises(ValidationError):
        Rule.model_validate(rule)


def test_duplicate_rule_ids_rejected():
    rules = inputs()[-1]
    rules["rules"].append(copy.deepcopy(rules["rules"][0]))
    with pytest.raises(ValidationError):
        RuleSet.model_validate(rules)


@pytest.mark.parametrize("domain", ["example.com", "sub.example.org", "regulator.invalid", "policy.example", "policy.test"])
def test_real_looking_rule_cannot_use_reserved_example_domains(domain):
    i, s, e, r = inputs()
    i["is_synthetic"] = s["is_synthetic"] = False
    for rule, item in zip(r["rules"], e, strict=True):
        rule["is_synthetic"] = item["is_synthetic"] = False
        rule["source_url"] = item["source_url"] = "https://" + domain + "/policy"
    with pytest.raises(ValueError, match="reserved"):
        evaluate_compliance(i, s, e, r, checked_at=STAMP)
    for item in e:
        item["assertion_status"] = "unverified"
    result = evaluate_compliance(i, s, e, r, checked_at=STAMP)
    assert {row["status"] for row in result["checks"]} == {"needs_verification"}


def test_real_case_cannot_take_synthetic_rules():
    with pytest.raises(ValueError, match="synthetic"):
        evaluate(change=lambda i, s, e, r: i.update(is_synthetic=False))


def test_engine_snapshots_rules_and_validator_rejects_entire_check_tamper(tmp_path):
    i, s, e, r = inputs()
    store = CaseStore.create(tmp_path / "case", i, s)
    store.write("evidence.jsonl", e)
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps(r))
    result = check_case(store, rules_path, checked_at=STAMP)
    assert result["checked_at"] == STAMP
    assert (store.path / "rules_snapshot.json").is_file()
    assert validate_case(store.path) == []
    result["checks"][0]["rationale"] = "Unreviewed replacement rationale"
    store.write("compliance.json", result)
    assert any("recomputed" in error for error in validate_case(store.path))


def test_cannot_force_a_pass_by_editing_required_values_or_snapshot_binding(tmp_path):
    i, s, e, r = inputs()
    s["product_attributes"]["tracking_label_present"] = False
    store = CaseStore.create(tmp_path / "case", i, s)
    store.write("evidence.jsonl", e)
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps(r))
    result = check_case(store, rules_path, checked_at=STAMP)
    assert result["checks"][0]["status"] == "fail"
    result["checks"][0].update(status="pass", severity="info")
    store.write("compliance.json", result)
    assert any("recomputed" in error for error in validate_case(store.path))
    snapshot = store.read("rules_snapshot.json")
    snapshot["rules"][0]["required_values"]["tracking_label_present"] = False
    store.write("rules_snapshot.json", snapshot)
    assert any("snapshot" in error for error in validate_case(store.path))


def test_checked_at_override_rejected_for_real_case_or_mixed_rules(tmp_path):
    i, s, e, r = inputs()
    r["rules"][0]["is_synthetic"] = False
    store = CaseStore.create(tmp_path / "case", i, s)
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps(r))
    with pytest.raises(ValueError, match="synthetic"):
        check_case(store, rules_path, checked_at=STAMP)


def test_live_research_rules_cannot_pass_without_effective_and_current_basis():
    i, s, _, _ = inputs()
    i["is_synthetic"] = s["is_synthetic"] = False
    rules = json.loads((ROOT / "rules/live-research-2026-10-27.json").read_text())
    result = evaluate_compliance(i, s, [], rules, checked_at=STAMP)
    assert {row["status"] for row in result["checks"]} == {"needs_verification"}
