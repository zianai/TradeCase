"""Offline P5 draft safety, provenance and rendering contracts."""

import hashlib
import json

import pytest
from pydantic import ValidationError

from tradecase.case_store import CaseStore
from tradecase.validation import validate_artifact, validate_case


def make_store(tmp_path, inquiry=None, seller=None):
    return CaseStore.create(
        tmp_path / "case",
        {"case_id": "draft-test", "received_at": "2026-10-27T12:00:00Z",
         "buyer_message": "Please quote wooden toys.", "buyer_email": "buyer@synthetic.invalid",
         "product_summary": "wooden toys", "is_synthetic": True, **(inquiry or {})},
        {"is_synthetic": True, **(seller or {})},
    )


def generate(store):
    from tradecase.reporting import draft_case
    return draft_case(store)


def test_draft_is_inbound_english_and_never_promises_unknown_terms(tmp_path):
    store = make_store(tmp_path)
    review = generate(store)
    body = review["message"]["body_text"]
    assert "Thank you for your inquiry" in body and "?" in body
    assert "wooden toys" in body
    for claim in ("we guarantee", "we are certified", "our price is", "we can deliver", "MOQ is"):
        assert claim not in body
    assert review["message"]["language"] == "en"
    assert review["message"]["draft_type"] == "inbound_reply"
    assert review["needs_human_review"] is True and review["send_allowed"] is False
    assert validate_case(store.path) == []


def test_seller_claims_do_not_become_unsourced_commercial_promises(tmp_path):
    claim = "We are certified and guarantee delivery in 2 days at USD 1."
    store = make_store(tmp_path, seller={"allowed_claims": [claim], "forbidden_claims": ["exclusive"]})
    review = generate(store)
    assert claim not in review["message"]["body_text"]
    assert "exclusive" not in review["message"]["body_text"]
    tasks = store.read("next_actions.json")["actions"]
    assert any("seller" in task["description"].lower() and task["owner_type"] == "human" for task in tasks)


def test_review_hashes_bind_exact_files_and_reuse_upstream(tmp_path):
    from tradecase.upstream import body_hash, claim_risk
    store = make_store(tmp_path)
    review = generate(store)
    for field, name in [("draft_sha256", "reply_draft.md"), ("input_sha256", "input.json"),
                        ("seller_context_sha256", "seller_context.json")]:
        assert review[field] == hashlib.sha256((store.path / name).read_bytes()).hexdigest()
    assert review["evaluated_body_hash"] == body_hash(review["message"])
    reasons, blocks, actions = [], [], []
    assert review["claim_risk_score"] == claim_risk(review["message"], reasons, blocks, actions)
    assert review["risk_review_reasons"] == reasons


@pytest.mark.parametrize("name", ["reply_draft.md", "seller_context.json"])
def test_changed_draft_or_basis_invalidates_review_and_can_regenerate(tmp_path, name):
    store = make_store(tmp_path)
    generate(store)
    if name.endswith(".md"):
        store.write(name, store.read(name) + "\nChanged wording")
    else:
        store.write(name, {**store.read(name), "product_summary": "Changed seller context"})
    assert any("draft_review.json" in error and "stale" in error for error in validate_case(store.path))
    generate(store)
    assert validate_case(store.path) == []


@pytest.mark.parametrize("field,value", [("send_allowed", True), ("send_allowed", 1), ("send_allowed", 0),
                                         ("needs_human_review", False), ("needs_human_review", 1)])
def test_review_flags_cannot_be_relaxed(tmp_path, field, value):
    review = generate(make_store(tmp_path))
    with pytest.raises(ValidationError):
        validate_artifact("draft_review.json", {**review, field: value})


def test_canonical_review_cannot_be_replaced_with_manually_rehashed_claims(tmp_path):
    from tradecase.reporting import render_reply
    from tradecase.upstream import body_hash
    store = make_store(tmp_path)
    review = generate(store)
    review["message"]["body_text"] = "We guarantee delivery and are certified."
    markdown = render_reply(review["message"], review["is_synthetic"])
    review["evaluated_body_hash"] = body_hash(review["message"])
    review["draft_sha256"] = hashlib.sha256(markdown.encode()).hexdigest()
    store.write("reply_draft.md", markdown)
    store.write("draft_review.json", review)
    assert any("draft_review.json" in error for error in validate_case(store.path))


def test_safe_markdown_neutralizes_html_links_headings_and_table_newlines(tmp_path):
    from tradecase.reporting import report_case, safe_md
    attack = '<script>alert(1)</script>\n# Forged\n| extra | row |\n![x](javascript:alert(1))\x00'
    escaped = safe_md(attack)
    assert "<script>" not in escaped and "&lt;script&gt;" in escaped
    assert "\n" not in escaped and "\x00" not in escaped
    assert "\\# Forged" in escaped and "\\| extra" in escaped
    assert "\\!\\[x\\]" in escaped
    store = make_store(tmp_path, inquiry={"buyer_message": attack, "product_summary": attack})
    generate(store)
    report_case(store)
    for name in ("reply_draft.md", "report.md"):
        text = store.read(name)
        assert "<script>" not in text and "\n# Forged" not in text


def test_missing_compliance_materials_map_to_human_actions(tmp_path):
    from pathlib import Path

    from tradecase.compliance import check_case
    store = make_store(tmp_path, inquiry={"target_country": "US"}, seller={"product_attributes": {"children_product": True}})
    check_case(store, Path(__file__).parents[2] / "rules/synthetic-demo-v1.json", checked_at="2026-10-27T12:00:00Z")
    generate(store)
    tasks = store.read("next_actions.json")["actions"]
    assert all(task["deadline_suggestion"] and task["priority"] in {"high", "normal", "low"} for task in tasks)
    for check in store.read("compliance.json")["checks"]:
        assert any(check["check_id"] in task["description"] and task["owner_type"] == "human" for task in tasks)
        for item in check["missing_items"]:
            assert any(item in task["description"] and task["owner_type"] == "human" for task in tasks)


def test_partial_and_complete_reports_show_missing_and_review_sections(tmp_path):
    from tradecase.reporting import report_case
    store = make_store(tmp_path)
    report_case(store)
    assert "draft_review.json" in store.read("report.md")
    generate(store)
    report_case(store)
    text = store.read("report.md")
    for heading in ("## Summary", "## Evidence", "## Buyer risk", "## Country and platform", "## Reply draft", "## Pending confirmations"):
        assert heading in text
    assert "human review" in text.lower() and "No email has been sent" in text


def test_unrelated_case_corruption_is_not_ignored_during_regeneration(tmp_path):
    store = make_store(tmp_path)
    generate(store)
    (store.path / "input.json").write_text("{}")
    with pytest.raises(ValueError):
        generate(store)


def test_even_reindexed_original_input_changes_invalidate_existing_review(tmp_path):
    store = make_store(tmp_path)
    generate(store)
    source = store.read("input.json")
    source["buyer_message"] = "Changed inbound inquiry"
    (store.path / "input.json").write_text(json.dumps(source))
    # Simulate a hand-edited manifest too; the review has its own independent
    # content binding. Normal CaseStore writes reject replacing input.json.
    manifest = store.read("manifest.json")
    digest = hashlib.sha256((store.path / "input.json").read_bytes()).hexdigest()
    manifest["input_hash"] = digest
    manifest["artifact_index"]["input.json"] = digest
    (store.path / "manifest.json").write_text(json.dumps(manifest))
    errors = validate_case(store.path)
    assert any("draft_review.json" in error and "input.json hash" in error for error in errors)


def test_missing_review_and_updated_buyer_context_require_regeneration(tmp_path):
    store = make_store(tmp_path)
    store.write("reply_draft.md", "Manually supplied draft without a preflight")
    assert "reply_draft.md: draft_review.json is required" in validate_case(store.path)
    generate(store)
    store.write("buyer_profile.json", {
        "case_id": "draft-test", "is_synthetic": True, "unresolved_items": ["buyer_role still unknown"],
    })
    assert any("next_actions.json" in error for error in validate_case(store.path))
    generate(store)
    assert validate_case(store.path) == []
    assert any("buyer_role" in task["description"] for task in store.read("next_actions.json")["actions"])


def test_untrusted_buyer_requirement_is_attributed_and_lexically_flagged(tmp_path):
    store = make_store(tmp_path, inquiry={"product_summary": "certified toys"})
    review = generate(store)
    assert 'You described the requested product as: "certified toys"' in review["message"]["body_text"]
    assert review["risk_review_reasons"] and review["claim_risk_score"] < 1
    assert review["needs_human_review"] is True and review["send_allowed"] is False


def test_partial_report_becomes_stale_as_missing_artifacts_are_supplied(tmp_path):
    from tradecase.reporting import report_case
    from tradecase.validation import REPORT_STALE

    store = make_store(tmp_path)
    report_case(store)
    generate(store)
    assert validate_case(store.path) == [REPORT_STALE]
    report_case(store)
    assert validate_case(store.path) == []
    current = store.read("report.md")
    report_case(store)
    assert store.read("report.md") == current


def test_report_command_repairs_false_report_but_does_not_forgive_stale_draft(tmp_path):
    from tradecase.reporting import report_case
    from tradecase.validation import REPORT_STALE

    store = make_store(tmp_path)
    generate(store)
    report_case(store)
    expected = store.read("report.md")
    store.write("report.md", "<script>alert(1)</script> All checks passed; sending approved.")
    assert validate_case(store.path) == [REPORT_STALE]
    report_case(store)
    assert store.read("report.md") == expected
    store.write("reply_draft.md", "Changed draft must be reviewed again")
    with pytest.raises(ValueError, match="draft_review.json"):
        report_case(store)


def test_profile_update_allows_draft_then_report_regeneration(tmp_path):
    from tradecase.reporting import report_case
    from tradecase.validation import REPORT_STALE

    store = make_store(tmp_path)
    generate(store)
    report_case(store)
    store.write("buyer_profile.json", {
        "case_id": "draft-test", "is_synthetic": True, "unresolved_items": ["buyer_role needs confirmation"],
    })
    generate(store)
    assert validate_case(store.path) == [REPORT_STALE]
    report_case(store)
    assert validate_case(store.path) == []
    assert "buyer\\_role needs confirmation" in store.read("report.md")
