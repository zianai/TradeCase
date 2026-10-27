"""Deterministic priority rules and refusal to launder weak sources."""

import copy
import hashlib
import json

import pytest

from tradecase.assessment import assess_case, calculate_assessment
from tradecase.case_store import CaseStore
from tradecase.validation import validate_case

STAMP = "2026-10-27T16:00:00Z"
NAMES = ["verified_identity", "buyer_role_evidence", "product_fit_evidence", "inquiry_specificity", "contactability"]


def strong_inputs():
    inquiry = dict(case_id="scoring-case", received_at=STAMP,
                   buyer_message="Please quote 500 steel widgets for US distribution.", is_synthetic=True)
    candidate = dict(candidate_id="company-1", name="Example Buyer", website="https://buyer.example/",
                     identity_status="supported", evidence_ids=["identity"], is_synthetic=True)
    rows = []
    for eid, text in [
        ("identity", "Example Buyer is the trading name of Example Buyer Ltd."),
        ("role", "We distribute steel widgets to industrial customers."),
        ("fit", "We stock steel widgets."),
        ("specific", inquiry["buyer_message"]),
        ("contact", "Contact our purchasing team at buying@buyer.example."),
    ]:
        rows.append(dict(evidence_id=eid, claim=text, excerpt=text, source_url="https://buyer.example/about",
                         source_type="official_site", captured_at=STAMP, retrieved_by="synthetic-fixture",
                         entity_candidate_id="company-1", assertion_status="supported", is_synthetic=True))
    rows[3].update(source_type="user_provided", source_url=None, local_snapshot_ref="input.json",
                   entity_candidate_id=None)
    profile = dict(case_id="scoring-case", candidate_ids=["company-1"], selected_candidate_id="company-1",
                   is_synthetic=True, contacts=[dict(email="buying@buyer.example", source_class="public",
                   source_url="https://buyer.example/about", evidence_ids=["contact"], verified=False)])
    signals = {name: {"value": "supported", "evidence_ids": [eid]} for name, eid in zip(
        NAMES, ["identity", "role", "fit", "specific", "contact"], strict=True)}
    return inquiry, profile, [candidate], rows, signals


def calculate(*, change=None):
    args = strong_inputs()
    if change:
        change(*args)
    return calculate_assessment(*args)


def test_strong_case_scores_100_and_is_repeatably_identical():
    args = strong_inputs()
    before = copy.deepcopy(args)
    first = calculate_assessment(*args)
    second = calculate_assessment(*args)
    assert first["score"] == 100
    assert first["evidence_coverage"] == 1
    assert first["decision"] == "high_priority"
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert args == before
    assert first["rule_version"] == "priority-v1"


def test_unknown_signals_are_not_optimistic_default_points():
    inquiry, profile, candidates, evidence, _ = strong_inputs()
    result = calculate_assessment(inquiry, profile, candidates, evidence, {})
    assert result["score"] is None
    assert result["evidence_coverage"] == 0
    assert result["decision"] == "needs_review"
    assert len(result["missing_information"]) == 5


def test_weighted_coverage_boundary_and_identity_gate():
    args = strong_inputs()
    args[-1].pop("product_fit_evidence")
    args[-1].pop("contactability")
    result = calculate_assessment(*args)
    assert result["evidence_coverage"] == 0.65
    assert result["score"] == 65
    args[-1].pop("verified_identity")
    result = calculate_assessment(*args)
    assert result["score"] is None
    assert result["decision"] == "needs_review"


@pytest.mark.parametrize("mutation", [
    lambda i, p, c, e, s: s.update(unknown_signal={"value": "unknown"}),
    lambda i, p, c, e, s: s["verified_identity"].update(evidence_ids=["missing"]),
    lambda i, p, c, e, s: e[0].update(source_type="search_snippet"),
    lambda i, p, c, e, s: e[0].update(source_type="directory"),
    lambda i, p, c, e, s: e[0].update(entity_candidate_id="another-company"),
    lambda i, p, c, e, s: e[0].update(assertion_status="unverified"),
    lambda i, p, c, e, s: s["verified_identity"].update(evidence_ids=[]),
])
def test_invalid_agent_signals_are_rejected(mutation):
    with pytest.raises(ValueError):
        calculate(change=mutation)


def test_inferred_email_cannot_score_contactability():
    def change(i, p, c, e, s):
        p["contacts"][0]["source_class"] = "inferred"
    with pytest.raises(ValueError, match="public"):
        calculate(change=change)


def test_public_email_not_mailbox_verified_can_score_contactability():
    result = calculate()
    assert result["score"] == 100
    assert strong_inputs()[1]["contacts"][0]["verified"] is False


def test_inquiry_specificity_must_quote_actual_input():
    def change(i, p, c, e, s):
        e[3]["excerpt"] = "Fabricated order quantity 9 million."
    with pytest.raises(ValueError, match="inquiry"):
        calculate(change=change)


def test_ambiguity_never_becomes_high_priority():
    def change(i, p, c, e, s):
        p["unresolved_items"] = ["domain mismatch between inquiry and selected entity"]
    result = calculate(change=change)
    assert result["score"] == 100
    assert result["decision"] == "needs_review"
    assert "BUYER_UNRESOLVED" in result["reason_codes"]


def test_contradiction_requires_review_and_does_not_score():
    args = strong_inputs()
    args[-1]["product_fit_evidence"]["value"] = "contradicted"
    args[3][2]["assertion_status"] = "contradicted"
    result = calculate_assessment(*args)
    assert result["score"] == 75
    assert result["evidence_coverage"] == 1
    assert result["decision"] == "needs_review"


def test_assess_case_writes_computed_artifact_and_validator_rejects_tamper(tmp_path):
    inquiry, profile, candidates, evidence, signals = strong_inputs()
    store = CaseStore.create(tmp_path / "case", inquiry, {"is_synthetic": True})
    store.write("candidates.jsonl", candidates)
    store.write("evidence.jsonl", evidence)
    store.write("buyer_profile.json", profile)
    store.write("assessment.json", dict(case_id=inquiry["case_id"], signals=signals, is_synthetic=True))
    assess_case(store)
    result = store.read("assessment.json")
    assert result["score"] == 100
    assert validate_case(store.path) == []
    result["score"] = 99
    store.write("assessment.json", result)
    assert any("derivation" in error or "recomputed" in error for error in validate_case(store.path))


def test_assess_case_with_no_agent_signals_persists_unknown_result(tmp_path):
    inquiry = strong_inputs()[0]
    store = CaseStore.create(tmp_path / "case", inquiry, {"is_synthetic": True})
    assess_case(store)
    result = store.read("assessment.json")
    assert result["score"] is None
    assert result["decision"] == "needs_review"
    assert validate_case(store.path) == []


def test_validator_checks_score_even_after_manifest_hashes_are_rewritten(tmp_path):
    inquiry, profile, candidates, evidence, signals = strong_inputs()
    store = CaseStore.create(tmp_path / "case", inquiry, {"is_synthetic": True})
    for name, data in [("candidates.jsonl", candidates), ("evidence.jsonl", evidence),
                       ("buyer_profile.json", profile)]:
        store.write(name, data)
    result = calculate_assessment(inquiry, profile, candidates, evidence, signals)
    result["score"] = 90
    store.write("assessment.json", result)
    manifest = store.read("manifest.json")
    manifest["artifact_index"]["assessment.json"] = hashlib.sha256((store.path / "assessment.json").read_bytes()).hexdigest()
    (store.path / "manifest.json").write_text(json.dumps(manifest))
    assert any("recomputed" in error for error in validate_case(store.path))


@pytest.mark.parametrize("mutation", [
    lambda i, p, c, e, s: p.update(website="https://other.example/"),
    lambda i, p, c, e, s: p.update(domain="other.example"),
    lambda i, p, c, e, s: (p.update(country="CA"), c[0].update(country="US")),
    lambda i, p, c, e, s: c[0].update(domain="other.example"),
])
def test_entity_fields_cannot_hide_conflict_behind_supported_signals(mutation):
    result = calculate(change=mutation)
    assert result["score"] == 100
    assert result["decision"] == "needs_review"
    assert "ENTITY_FIELD_CONFLICT" in result["reason_codes"]


@pytest.mark.parametrize("mutation", [
    lambda i, p, c, e, s: i.update(buyer_email="purchasing@other.example"),
    lambda i, p, c, e, s: i.update(buyer_website_hint="https://other.example/"),
])
def test_inquiry_domain_mismatch_requires_review(mutation):
    result = calculate(change=mutation)
    assert result["decision"] == "needs_review"
    assert "INQUIRY_DOMAIN_CONFLICT" in result["reason_codes"]


def test_public_email_is_not_treated_as_a_corporate_website():
    result = calculate(change=lambda i, p, c, e, s: i.update(buyer_email="buyer@gmail.com"))
    assert result["decision"] == "high_priority"
    assert "INQUIRY_DOMAIN_CONFLICT" not in result["reason_codes"]


def test_parent_and_subdomain_are_not_an_automatic_identity_conflict():
    result = calculate(change=lambda i, p, c, e, s: i.update(buyer_email="buyer@purchasing.buyer.example"))
    assert result["decision"] == "high_priority"
