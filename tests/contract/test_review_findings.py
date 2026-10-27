"""Regression cases found by independent read-only P3 review."""

import json

import pytest

from tradecase.case_store import CaseStore
from tradecase.validation import validate_case


def initial_store(tmp_path):
    return CaseStore.create(tmp_path / "case", {
        "case_id": "review-case", "received_at": "2026-10-27T16:00:00Z",
        "buyer_message": "Synthetic review fixture", "is_synthetic": True,
    }, {"is_synthetic": True})


def test_recovery_cannot_roll_back_newer_revision(tmp_path):
    store = initial_store(tmp_path)
    names = ["input.json", "seller_context.json", "events.jsonl", "manifest.json"]
    old_journal = {
        "revision": store.read("manifest.json")["revision"],
        "files": {name: (store.path / name).read_text() for name in names},
    }
    store.transition("running", "research")
    store.write("search_plan.md", "Preserve this more recent investigation and audit history.")
    current_manifest = (store.path / "manifest.json").read_bytes()
    current_events = (store.path / "events.jsonl").read_bytes()
    (store.path / ".transaction.json").write_text(json.dumps(old_journal))
    with pytest.raises(ValueError, match="revision|stale|rollback"):
        store.recover()
    assert (store.path / "manifest.json").read_bytes() == current_manifest
    assert (store.path / "events.jsonl").read_bytes() == current_events


def test_invalid_recovery_bundle_does_not_overwrite_original_inquiry(tmp_path):
    store = initial_store(tmp_path)
    original = (store.path / "input.json").read_bytes()
    changed = store.read("input.json")
    changed["buyer_message"] = "Corrupted but locally schema-valid after-image"
    bad_journal = {
        "revision": store.read("manifest.json")["revision"] + 1,
        "files": {"input.json": json.dumps(changed)},
    }
    marker = store.path / ".transaction.json"
    marker.write_text(json.dumps(bad_journal))
    with pytest.raises(ValueError):
        store.recover()
    assert (store.path / "input.json").read_bytes() == original
    assert marker.exists(), "invalid transaction must remain available for diagnosis"


def test_recovery_rejects_complete_row_without_final_newline_before_writing(tmp_path):
    store = initial_store(tmp_path)
    original_events = (store.path / "events.jsonl").read_bytes()
    manifest = store.read("manifest.json")
    manifest["revision"] += 1
    old_event = store.read("events.jsonl")[-1]
    event = {**old_event, "event_id": "event-next", "revision": manifest["revision"]}
    journal = {
        "revision": manifest["revision"],
        "files": {
            "events.jsonl": original_events.decode() + json.dumps(event),
            "manifest.json": json.dumps(manifest),
        },
    }
    marker = store.path / ".transaction.json"
    marker.write_text(json.dumps(journal))
    with pytest.raises(ValueError):
        store.recover()
    assert (store.path / "events.jsonl").read_bytes() == original_events
    assert marker.exists()


def test_snapshot_content_is_not_silently_unbound(tmp_path):
    store = initial_store(tmp_path)
    snapshot = store.path / "snapshot.txt"
    snapshot.write_text("Original quoted source")
    store.write("evidence.jsonl", [{
        "evidence_id": "ev-local", "claim": "Original quoted source", "excerpt": "Original quoted source",
        "source_type": "user_provided", "captured_at": "2026-10-27T16:00:00Z", "retrieved_by": "offline_fixture",
        "assertion_status": "supported", "is_synthetic": True, "local_snapshot_ref": "snapshot.txt",
    }])
    # Either require a snapshot digest in the artifact index or reject a quote
    # whose declared local snapshot no longer preserves the supporting source.
    snapshot.write_text("Replaced source that no longer contains the original quote")
    assert any("snapshot" in error for error in validate_case(store.path))


def ready_store(tmp_path):
    from pathlib import Path

    from tradecase.assessment import calculate_assessment

    fixture = json.loads((Path(__file__).parents[2] / "fixtures/case_strong/fixture.json").read_text())
    inquiry = {**fixture["inquiry"], "case_id": "review-complete", "received_at": "2026-10-27T16:00:00Z"}
    profile = {**fixture["profile"], "case_id": inquiry["case_id"]}
    evidence = fixture["evidence"]
    for row in evidence:
        if row.get("source_url"):
            row["local_snapshot_ref"] = None
    checks = []
    for kind, source_type in [("country", "government"), ("platform", "platform_official")]:
        url = f"https://policy.example/{kind}"
        evidence.append({
            "evidence_id": "rule-" + kind, "claim": "Synthetic rule", "excerpt": "Synthetic rule",
            "source_type": source_type, "source_url": url, "captured_at": "2026-10-27T16:00:00Z",
            "retrieved_by": "offline_fixture", "assertion_status": "supported", "is_synthetic": True,
        })
        checks.append({
            "check_id": "check-" + kind, "check_type": kind, "jurisdiction": "US", "platform": "amazon_us",
            "product_scope": "Synthetic fixture", "rule_id": "rule-" + kind, "rule_version": "fixture-v1",
            "checked_at": "2026-10-27T16:00:00Z", "source_url": url, "status": "pass", "severity": "info",
            "rationale": "Synthetic offline fixture only", "suggested_action": "Review official current policy",
            "evidence_ids": ["rule-" + kind], "is_synthetic": True,
        })
    store = CaseStore.create(tmp_path / "complete", inquiry, fixture["seller"])
    for name, data in [
        ("candidates.jsonl", fixture["candidates"]), ("evidence.jsonl", evidence), ("buyer_profile.json", profile),
        ("assessment.json", calculate_assessment(inquiry, profile, fixture["candidates"], evidence, fixture["signals"])),
        ("compliance.json", {"case_id": inquiry["case_id"], "checks": checks, "is_synthetic": True}),
        ("next_actions.json", {"case_id": inquiry["case_id"], "is_synthetic": True}),
        ("search_plan.md", "Synthetic source research plan"), ("reply_draft.md", "Synthetic draft, do not send"),
        ("report.md", "Synthetic offline report"),
    ]:
        store.write(name, data)
    store.transition("running", "report")
    assert validate_case(store.path, strict=True) == []
    return store


@pytest.mark.parametrize("kwargs", [{"error": "still failed"}, {"blockers": ["still blocked"]}])
def test_completion_cannot_inject_blockers_after_prevalidation(tmp_path, kwargs):
    store = ready_store(tmp_path)
    with pytest.raises(ValueError):
        store.transition("completed", "done", **kwargs)
    assert store.read("manifest.json")["state"] == "running"
    assert validate_case(store.path, strict=True) == []
