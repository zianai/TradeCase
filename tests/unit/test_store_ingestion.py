import json

import pytest

from tradecase.case_store import CaseStore
from tradecase.ingestion import parse_inquiry
from tradecase.validation import validate_case


def test_eml_preserves_raw_and_attachment_metadata(tmp_path):
    p = tmp_path / "inquiry.eml"
    p.write_bytes(
        b"From: Buyer <buyer@acme.invalid>\r\nDate: Tue, 27 Oct 2026 10:00:00 +0000\r\nSubject: RFQ\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nPlease quote 100 units.\r\n"
    )
    row = parse_inquiry(p, "one")
    assert row.buyer_email == "buyer@acme.invalid"
    assert "100 units" in row.buyer_message
    assert row.raw_sha256 and row.raw_content


def test_store_initial_valid_and_no_overwrite(tmp_path):
    p = tmp_path / "i.txt"
    p.write_text("Synthetic RFQ")
    store = CaseStore.create(tmp_path / "case", parse_inquiry(p, "case"), {"is_synthetic": False})
    assert validate_case(store.path) == []
    with pytest.raises(FileExistsError):
        CaseStore.create(store.path, parse_inquiry(p, "case"), {})
    assert validate_case(store.path, strict=True)


def test_atomic_revisions_and_failure_resume(tmp_path):
    p = tmp_path / "i.txt"
    p.write_text("Synthetic RFQ")
    store = CaseStore.create(tmp_path / "case", parse_inquiry(p, "case"), {})
    store.transition("running", "research")
    store.transition("failed", "research", error="offline interruption")
    store.transition("running", "research")
    assert validate_case(store.path) == []
    events = store.read("events.jsonl")
    assert len({e["revision"] for e in events}) == len(events)
    assert store.read("manifest.json")["state"] == "running"
    with pytest.raises(ValueError):
        store.transition("completed", "done")


def test_reject_path_and_symlink(tmp_path):
    p = tmp_path / "i.txt"
    p.write_text("Synthetic RFQ")
    store = CaseStore.create(tmp_path / "case", parse_inquiry(p, "case"), {})
    with pytest.raises(ValueError):
        store.write("../escape.json", {})
    (store.path / "evidence.jsonl").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(ValueError):
        store.write("evidence.jsonl", [])


def test_json_input_unknown_not_invented(tmp_path):
    p = tmp_path / "i.json"
    p.write_text(json.dumps({"buyer_message": "Need lamps"}))
    row = parse_inquiry(p, "i")
    assert row.platform is None and row.target_country is None


def test_transaction_rolls_forward_after_actual_write_failure(tmp_path, monkeypatch):
    import tradecase.case_store as module

    p = tmp_path / "i.txt"
    p.write_text("Synthetic RFQ")
    store = CaseStore.create(tmp_path / "case", parse_inquiry(p, "case"), {})
    original = module.atomic_write

    def interrupted(path, data):
        if path.name == "search_plan.md" and ".history" not in path.parts:
            raise OSError("simulated local I/O failure, offline test")
        original(path, data)

    with monkeypatch.context() as patch:
        patch.setattr(module, "atomic_write", interrupted)
        with pytest.raises(OSError):
            store.write("search_plan.md", "Research public sources only")
    assert (store.path / ".transaction.json").exists()
    store.recover()
    assert store.read("search_plan.md") == "Research public sources only"
    assert not (store.path / ".transaction.json").exists()
    assert validate_case(store.path) == []


def test_bad_encoding_and_attachment_remain_data(tmp_path):
    import base64
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = "buyer@acme.invalid"
    msg.set_content("Please quote")
    msg.add_attachment(b"#!/bin/sh\nexit 99", maintype="application", subtype="octet-stream", filename="../payload.sh")
    p = tmp_path / "i.eml"
    p.write_bytes(msg.as_bytes())
    row = parse_inquiry(p, "case")
    assert base64.b64decode(row.raw_bytes_base64) == p.read_bytes()
    assert row.files[0].filename == "../payload.sh"
    assert not (tmp_path / "payload.sh").exists()


def test_snapshot_is_journaled_and_hashed(tmp_path):
    p = tmp_path / "i.txt"
    p.write_text("Synthetic RFQ")
    store = CaseStore.create(tmp_path / "case", parse_inquiry(p, "case"), {})
    store.save_snapshot("snapshots/public-page.txt", "untrusted text")
    assert store.read("manifest.json")["artifact_index"]["snapshots/public-page.txt"]
    assert validate_case(store.path) == []
    (store.path / "snapshots/public-page.txt").write_text("tampered")
    assert any("hash mismatch" in error for error in validate_case(store.path))
