"""Journal recovery must preserve edits made after an actual I/O interruption."""

import json
from pathlib import Path

import pytest

import tradecase.case_store as module
from tradecase.case_store import CaseStore
from tradecase.validation import validate_case


def create_store(tmp_path):
    return CaseStore.create(tmp_path / "case", {
        "case_id": "case", "received_at": "2026-10-27T12:00:00Z",
        "buyer_message": "Synthetic interrupted transaction", "is_synthetic": True,
    }, {"is_synthetic": True})


def interrupt_plan(store, monkeypatch):
    original = module.atomic_write

    def interrupt(path, raw):
        if path == store.path / "search_plan.md":
            raise OSError("synthetic fault before replacement")
        return original(path, raw)

    with monkeypatch.context() as patch:
        patch.setattr(module, "atomic_write", interrupt)
        with pytest.raises(OSError):
            store.write("search_plan.md", "Queued replacement")


def test_conflict_refusal_preserves_every_target_and_journal(tmp_path, monkeypatch):
    store = create_store(tmp_path)
    store.write("search_plan.md", "Original plan")
    interrupt_plan(store, monkeypatch)
    (store.path / "search_plan.md").write_text("Human intervening investigation")
    names = ["search_plan.md", "manifest.json", "events.jsonl", ".transaction.json"]
    before = {name: (store.path / name).read_bytes() for name in names}
    with pytest.raises(ValueError, match="conflict|changed"):
        store.recover()
    assert {name: (store.path / name).read_bytes() for name in names} == before


def test_initial_revision_preflights_all_targets_before_applying_any(tmp_path, monkeypatch):
    path = tmp_path / "case"
    original = module.atomic_write

    def interrupt(target, raw):
        if target == path / "input.json":
            raise OSError("synthetic interruption in first revision")
        return original(target, raw)

    with monkeypatch.context() as patch:
        patch.setattr(module, "atomic_write", interrupt)
        with pytest.raises(OSError):
            create_store(tmp_path)
    store = CaseStore(path)
    assert not (path / "input.json").exists()
    manual = b'{"company_name":"Human recovery note","is_synthetic":true}\n'
    (path / "seller_context.json").write_bytes(manual)
    before_events = (path / "events.jsonl").read_bytes() if (path / "events.jsonl").exists() else None
    with pytest.raises(ValueError, match="conflict|changed"):
        store.recover()
    assert not (path / "input.json").exists(), "preflight must finish before writing an earlier target"
    assert (path / "seller_context.json").read_bytes() == manual
    current_events = (path / "events.jsonl").read_bytes() if (path / "events.jsonl").exists() else None
    assert current_events == before_events
    assert (path / ".transaction.json").exists()


def test_applied_journal_replays_idempotently_when_marker_removal_failed(tmp_path, monkeypatch):
    store = create_store(tmp_path)
    original_unlink = Path.unlink

    def interrupt_marker(path, *args, **kwargs):
        if path == store.path / ".transaction.json":
            raise OSError("synthetic interruption after manifest commit")
        return original_unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", interrupt_marker)
        with pytest.raises(OSError):
            store.write("search_plan.md", "Committed content")
    before = {name: (store.path / name).read_bytes() for name in ["manifest.json", "events.jsonl", "search_plan.md"]}
    store.recover()
    assert {name: (store.path / name).read_bytes() for name in before} == before
    assert not (store.path / ".transaction.json").exists()
    assert validate_case(store.path) == []


def test_intervening_manifest_edit_is_not_silently_replaced(tmp_path, monkeypatch):
    store = create_store(tmp_path)
    store.write("search_plan.md", "Original plan")
    interrupt_plan(store, monkeypatch)
    manifest = store.read("manifest.json")
    manifest["current_stage"] = "human-investigation"
    (store.path / "manifest.json").write_text(json.dumps(manifest))
    before = (store.path / "manifest.json").read_bytes()
    with pytest.raises(ValueError, match="conflict|changed"):
        store.recover()
    assert (store.path / "manifest.json").read_bytes() == before
    assert store.read("search_plan.md") == "Original plan"
    assert (store.path / ".transaction.json").exists()
