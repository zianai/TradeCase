from datetime import datetime, timezone

from tradecase.procurement import evaluate_deadline

NOW = datetime(2026, 10, 27, 16, 0, tzinfo=timezone.utc)


def result(text, now=NOW):
    return evaluate_deadline(text, now=now)


def test_expired_offset_is_converted_to_utc():
    value = result("Deadline on: 20-Oct-2026 17:30 (GMT 2.00) Expired")
    assert value["status"] == "expired"
    assert value["deadline_utc"] == "2026-10-20T15:30:00Z"


def test_open_and_exact_boundary():
    text = "Deadline on: 28-Oct-2026 17:30 (GMT 2.00)"
    assert result(text)["status"] == "open"
    assert result(text, datetime(2026, 10, 28, 15, 30, tzinfo=timezone.utc))["status"] == "expired"


def test_unknown_timezone_and_conflicting_deadlines_fail_closed():
    assert result("Deadline on: 28-Oct-2026 17:30 (Eastern Time)")["status"] == "needs_review"
    text = "Deadline on: 30-Aug-2026 00:00 (GMT 2.00)\nBid submission deadline: 30 August 2026, at 15:00 Jerusalem Time"
    value = result(text)
    assert value["status"] == "needs_review"
    assert "conflicting_or_unparsed_deadline" in value["reasons"]


def test_no_deadline_is_unknown():
    assert result("A public notice with no deadline.")["status"] == "needs_review"


def _procurement_store(tmp_path, deadline="Deadline on: 20-Oct-2026 17:30 (GMT 2.00)"):
    import json

    from tradecase.case_store import CaseStore

    store = CaseStore.create(
        tmp_path / "case",
        {
            "case_id": "test-procurement",
            "received_at": "2026-10-27T12:00:00Z",
            "buyer_message": "Public notice",
            "case_type": "procurement",
            "deadline_evidence_id": "deadline-1",
            "is_synthetic": True,
        },
        {"is_synthetic": True},
    )
    store.save_snapshot(
        "snapshots/notice.json",
        json.dumps(
            {
                "source_url": "https://agency.invalid/notice",
                "selected_lines": deadline,
            }
        ),
    )
    store.write(
        "evidence.jsonl",
        [
            {
                "evidence_id": "deadline-1",
                "claim": "published deadline",
                "source_url": "https://agency.invalid/notice",
                "source_type": "government",
                "captured_at": "2026-10-27T12:00:00Z",
                "excerpt": deadline,
                "retrieved_by": "offline-test",
                "assertion_status": "supported",
                "is_synthetic": True,
                "local_snapshot_ref": "snapshots/notice.json",
            }
        ],
    )
    return store


def test_expired_case_becomes_needs_review_and_gets_internal_draft(tmp_path):
    from tradecase.reporting import draft_case
    from tradecase.validation import validate_case

    store = _procurement_store(tmp_path)
    review = draft_case(store)
    assert store.read("manifest.json")["state"] == "needs_review"
    assert "procurement_deadline:expired" in store.read("manifest.json")["blockers"]
    assert review["procurement_basis_sha256"]
    assert review["message"]["recipient_email"] is None
    assert "Do not submit" in review["message"]["body_text"]
    assert "Thank you for your inquiry" not in review["message"]["body_text"]
    assert review["send_allowed"] is False
    assert validate_case(store.path) == []


def test_source_change_invalidates_draft_even_with_new_manifest_hash(tmp_path):
    import json

    from tradecase.reporting import draft_case
    from tradecase.validation import validate_case

    store = _procurement_store(tmp_path)
    draft_case(store)
    snapshot = {
        "source_url": "https://agency.invalid/notice",
        "selected_lines": "Deadline on: 20-Oct-2026 17:30 (GMT 2.00)\nAdditional source text",
    }
    store.save_snapshot("snapshots/notice.json", json.dumps(snapshot))
    assert any("draft_review.json: stale" in error for error in validate_case(store.path))
    draft_case(store)
    assert validate_case(store.path) == []


def test_unindexed_or_mismatched_source_never_becomes_open(tmp_path):
    import json

    from tradecase.procurement import case_deadline

    store = _procurement_store(tmp_path, "Deadline on: 28-Oct-2099 17:30 (GMT 2.00)")
    inquiry = store.read("input.json")
    evidence = store.read("evidence.jsonl")
    assert case_deadline(store.path, inquiry, evidence)["status"] == "open"
    (store.path / "snapshots/notice.json").write_text(
        json.dumps(
            {
                "source_url": "https://other.invalid/notice",
                "selected_lines": evidence[0]["excerpt"],
            }
        )
    )
    result = case_deadline(store.path, inquiry, evidence)
    assert result["status"] == "needs_review"
    assert "deadline_evidence_snapshot_mismatch" in result["reasons"]


def test_open_procurement_draft_asks_about_tender_without_promising_terms():
    from tradecase.reporting import compose_reply

    inquiry = {
        "case_id": "open-case",
        "received_at": "2026-10-27T12:00:00Z",
        "buyer_message": "Public notice",
        "case_type": "procurement",
        "is_synthetic": True,
    }
    message = compose_reply(inquiry, {"is_synthetic": True}, {"status": "open"})
    assert "procurement" in message["subject"].lower()
    assert "eligibility" in message["body_text"]
    assert "subject to internal confirmation" in message["body_text"]
    assert message["recipient_email"] is None
    assert "Thank you for your inquiry" not in message["body_text"]


def test_forged_completed_manifest_does_not_bypass_expired_gate(tmp_path):
    from tradecase.reporting import draft_case
    from tradecase.util import json_bytes
    from tradecase.validation import validate_case

    store = _procurement_store(tmp_path)
    draft_case(store)
    manifest = store.read("manifest.json")
    manifest.update(state="completed", blockers=[], error=None)
    (store.path / "manifest.json").write_bytes(json_bytes(manifest))
    errors = validate_case(store.path)
    assert any("procurement deadline expired or unverified" in error for error in errors)


def test_missing_deadline_evidence_stays_in_review(tmp_path):
    from tradecase.case_store import CaseStore
    from tradecase.reporting import draft_case

    store = CaseStore.create(
        tmp_path / "case",
        {
            "case_id": "missing-deadline",
            "received_at": "2026-10-27T12:00:00Z",
            "buyer_message": "Public tender",
            "case_type": "procurement",
            "is_synthetic": True,
        },
        {"is_synthetic": True},
    )
    review = draft_case(store)
    assert store.read("manifest.json")["state"] == "needs_review"
    assert "unverified or conflicting deadline" in review["message"]["body_text"]
    assert review["procurement_basis_sha256"] is None


def test_current_amendment_can_clear_only_the_expired_deadline_blocker(tmp_path):
    import json

    from tradecase.reporting import draft_case

    store = _procurement_store(tmp_path)
    draft_case(store)
    deadline = "Deadline on: 28-Oct-2099 17:30 (GMT 2.00)"
    store.save_snapshot(
        "snapshots/notice.json",
        json.dumps(
            {
                "source_url": "https://agency.invalid/notice",
                "selected_lines": deadline,
            }
        ),
    )
    evidence = store.read("evidence.jsonl")
    evidence[0]["excerpt"] = deadline
    store.write("evidence.jsonl", evidence)
    review = draft_case(store)
    assert "clarification" in review["message"]["subject"].lower()
    assert store.read("manifest.json")["state"] == "running"
    assert not any(b.startswith("procurement_deadline:") for b in store.read("manifest.json")["blockers"])


def test_existing_p7_notice_without_new_fields_fails_closed(tmp_path):
    from tradecase.case_store import CaseStore
    from tradecase.reporting import draft_case

    store = CaseStore.create(
        tmp_path / "case",
        {
            "case_id": "legacy-notice",
            "received_at": "2026-10-27T12:00:00Z",
            "buyer_message": "A public notice",
            "is_synthetic": True,
            "parsing_warnings": [
                "Public procurement notice excerpt; not a direct inquiry to the seller; contact omitted."
            ],
        },
        {"is_synthetic": True},
    )
    review = draft_case(store)
    assert store.read("manifest.json")["state"] == "needs_review"
    assert "unverified or conflicting deadline" in review["message"]["body_text"]


def test_deadline_evidence_id_alone_cannot_bypass_procurement_gate():
    from tradecase.procurement import is_procurement

    assert is_procurement({"case_type": "inquiry", "deadline_evidence_id": "deadline-1"})
