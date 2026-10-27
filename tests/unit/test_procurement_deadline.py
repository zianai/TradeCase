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


def test_named_iana_and_jerusalem_time_with_dst():
    winter = result("Deadline on: 15-Jan-2027 12:00 (America/New_York)")
    summer = result("Deadline on: 15-Jul-2027 12:00 (America/New_York)")
    jerusalem = result("Bid submission deadline: 30 August 2026, at 15:00 Jerusalem Time")
    assert winter["deadline_utc"] == "2027-01-15T17:00:00Z"
    assert summer["deadline_utc"] == "2027-07-15T16:00:00Z"
    assert jerusalem["deadline_utc"] == "2026-08-30T12:00:00Z"


def test_named_zone_dst_fold_and_gap_require_review():
    assert result("Deadline on: 01-Nov-2026 01:30 (America/New_York)")["status"] == "needs_review"
    assert result("Deadline on: 08-Mar-2026 02:30 (America/New_York)")["status"] == "needs_review"


def test_date_only_uses_latest_possible_bound_not_invented_deadline():
    text = "Deadline on: 28-Oct-2026 (America/New_York)"
    during = result(text, datetime(2026, 10, 28, 16, 0, tzinfo=timezone.utc))
    after = result(text, datetime(2026, 10, 29, 4, 0, tzinfo=timezone.utc))
    assert during["status"] == "needs_review"
    assert during["deadline_utc"] is None
    assert during["latest_possible_utc"] == "2026-10-29T04:00:00Z"
    assert after["status"] == "expired" and after["deadline_utc"] is None


def test_date_only_without_explicit_timezone_and_ambiguous_abbreviation_require_review():
    assert result("Deadline on: 2026-10-28")["status"] == "needs_review"
    assert result("Deadline on: 2026-10-01")["status"] == "expired"
    assert result("Deadline on: 2026-10-28 15:00 CST")["status"] == "needs_review"


def test_real_conflicting_deadlines_remain_unresolved():
    notice = (
        "Deadline on: 30-Aug-2026 00:00 (GMT 2.00)\nBid submission deadline: 30 August 2026, at 15:00 Jerusalem Time"
    )
    assert result(notice)["status"] == "needs_review"


def test_date_only_evidence_binding_and_visible_bound(tmp_path):
    from tradecase.procurement import case_deadline
    from tradecase.reporting import draft_case, report_case
    from tradecase.validation import validate_case

    store = _procurement_store(tmp_path, "Deadline on: 28-Oct-2099 (Asia/Jerusalem)")
    deadline = case_deadline(store.path, store.read("input.json"), store.read("evidence.jsonl"))
    assert deadline["status"] == "needs_review"
    assert deadline["deadline_utc"] is None
    assert deadline["latest_possible_utc"] and deadline["basis_sha256"]
    draft_case(store)
    assert store.read("manifest.json")["state"] == "needs_review"
    report_case(store)
    assert "not an exact deadline" in store.read("report.md")
    assert validate_case(store.path) == []


def test_truncated_deadline_citation_is_not_accepted(tmp_path):
    from tradecase.procurement import case_deadline

    store = _procurement_store(tmp_path, "Deadline on: 28-Oct-2099 17:30 (Europe/London)")
    evidence = store.read("evidence.jsonl")
    evidence[0]["excerpt"] = "Deadline on: 28-Oct-2099"
    store.write("evidence.jsonl", evidence)
    result = case_deadline(store.path, store.read("input.json"), store.read("evidence.jsonl"))
    assert result["status"] == "needs_review"
    assert result["basis_sha256"] is None


def test_distinct_named_zone_in_summer_and_winter():
    assert result("Deadline on: 2027-01-15 12:00 Europe/London")["deadline_utc"] == "2027-01-15T12:00:00Z"
    assert result("Deadline on: 2027-07-15 12:00 Europe/London")["deadline_utc"] == "2027-07-15T11:00:00Z"


def test_explicit_utc_date_only_boundary():
    text = "Deadline on: 2026-10-27 (UTC)"
    assert result(text, datetime(2026, 10, 27, 23, 59, tzinfo=timezone.utc))["status"] == "needs_review"
    assert result(text, datetime(2026, 10, 28, 0, 0, tzinfo=timezone.utc))["status"] == "expired"


def test_unzoned_date_only_uses_wide_utc_bound_without_guessing_timezone():
    text = "Deadline on: 2026-10-27"
    before = result(text, datetime(2026, 10, 28, 23, 59, tzinfo=timezone.utc))
    after = result(text, datetime(2026, 10, 29, 0, 0, tzinfo=timezone.utc))
    assert before["status"] == "needs_review" and before["deadline_utc"] is None
    assert before["latest_possible_utc"] == "2026-10-29T00:00:00Z"
    assert "date_only_timezone_unspecified" in before["reasons"]
    assert after["status"] == "expired" and after["deadline_utc"] is None


def test_unsupported_zone_and_date_overflow_fail_closed():
    assert result("Deadline on: 28-Oct-2026 17:30 (Mars/Olympus)")["status"] == "needs_review"
    assert result("Deadline on: 9999-12-31 (UTC)")["status"] == "needs_review"


def test_changed_named_zone_resolution_invalidates_existing_review(tmp_path, monkeypatch):
    from datetime import timedelta

    import tradecase.procurement as procurement
    from tradecase.reporting import draft_case
    from tradecase.validation import validate_case

    store = _procurement_store(tmp_path, "Deadline on: 28-Oct-2099 17:30 (America/New_York)")
    draft_case(store)
    assert validate_case(store.path) == []
    monkeypatch.setattr(procurement, "_zone", lambda _value: timezone(timedelta(hours=-6)))
    assert any("draft_review.json: stale" in error for error in validate_case(store.path))


def test_missing_timezone_database_fails_closed(monkeypatch):
    from zoneinfo import ZoneInfoNotFoundError

    import tradecase.procurement as procurement

    def unavailable(_zone):
        raise ZoneInfoNotFoundError("not installed")

    monkeypatch.setattr(procurement, "ZoneInfo", unavailable)
    assert result("Deadline on: 28-Oct-2026 15:00 (Asia/Jerusalem)")["status"] == "needs_review"


def test_common_explicit_city_time_aliases():
    assert result("Deadline on: 2027-01-15 12:00 Beijing Time")["deadline_utc"] == "2027-01-15T04:00:00Z"
    assert result("Deadline on: 2027-07-15 12:00 US Pacific Time")["deadline_utc"] == "2027-07-15T19:00:00Z"
    assert result("Deadline on: 2027-01-15 12:00 US Pacific Time")["deadline_utc"] == "2027-01-15T20:00:00Z"


def test_other_common_deadline_labels_still_flag_conflict():
    text = "Deadline on: 28-Oct-2026 17:00 (UTC)\nClosing date: 29-Oct-2026 17:00 (UTC)"
    assert result(text)["status"] == "needs_review"
    assert "conflicting_or_unparsed_deadline" in result(text)["reasons"]


def test_leap_day_and_out_of_range_offset():
    assert result("Deadline on: 2028-02-29 12:00 (UTC)")["deadline_utc"] == "2028-02-29T12:00:00Z"
    assert result("Deadline on: 2027-02-29 12:00 (UTC)")["status"] == "needs_review"
    assert result("Deadline on: 2027-01-15 12:00 (GMT+14.15)")["status"] == "needs_review"


def test_fractional_offsets_and_negative_zero():
    assert result("Deadline on: 2027-01-15 12:00 (GMT+5:45)")["deadline_utc"] == "2027-01-15T06:15:00Z"
    assert result("Deadline on: 2027-01-15 12:00 (GMT-0.30)")["deadline_utc"] == "2027-01-15T12:30:00Z"


def test_date_only_bound_follows_dst_change_on_that_date():
    value = result("Deadline on: 08-Mar-2026 (America/New_York)")
    assert value["latest_possible_utc"] == "2026-03-09T04:00:00Z"
    assert value["status"] == "expired"
