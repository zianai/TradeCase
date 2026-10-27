"""Bounded final independent review: reproducible artifact/recovery findings."""

from pathlib import Path

import pytest

from tradecase.case_store import CaseStore
from tradecase.compliance import check_case
from tradecase.demo import run_demo
from tradecase.reporting import draft_case
from tradecase.validation import validate_case

ROOT = Path(__file__).resolve().parents[2]


def test_updated_compliance_cannot_leave_old_pass_report_valid(tmp_path):
    out = tmp_path / "review-report"
    run_demo(ROOT / "fixtures/case_strong", out)
    store = CaseStore(out)
    original_report = store.read("report.md")
    assert all(check["status"] == "pass" for check in store.read("compliance.json")["checks"])
    store.transition("running", "review-update")
    seller = store.read("seller_context.json")
    seller["product_attributes"]["tracking_label_present"] = False
    store.write("seller_context.json", seller)
    changed = check_case(store, ROOT / "rules/synthetic-demo-v1.json", checked_at="2026-10-27T12:00:00Z")
    assert any(check["status"] == "fail" for check in changed["checks"])
    draft_case(store)
    assert store.read("report.md") == original_report
    errors = validate_case(store.path, strict=True)
    assert any("report.md" in error and ("stale" in error or "match" in error) for error in errors), errors


def test_recovery_does_not_silently_discard_intervening_file_edits(tmp_path, monkeypatch):
    import tradecase.case_store as module

    store = CaseStore.create(tmp_path / "recovery-case", {
        "case_id": "recovery-case", "received_at": "2026-10-27T12:00:00Z",
        "buyer_message": "SYNTHETIC recovery test", "is_synthetic": True,
    }, {"is_synthetic": True})
    store.write("search_plan.md", "Original saved plan")
    original_write = module.atomic_write

    def interrupted(path, raw):
        if path == store.path / "search_plan.md":
            raise OSError("SYNTHETIC interrupted file replacement")
        return original_write(path, raw)

    with monkeypatch.context() as patch:
        patch.setattr(module, "atomic_write", interrupted)
        with pytest.raises(OSError):
            store.write("search_plan.md", "Queued pre-interruption plan")
    assert (store.path / ".transaction.json").exists()
    manual_text = "Human edit after the interruption; preserve this investigation"
    (store.path / "search_plan.md").write_text(manual_text)
    try:
        store.recover()
    except ValueError:
        pass  # Refusing a conflict is an acceptable safe recovery outcome.
    preserved = (store.path / "search_plan.md").read_text() == manual_text or any(
        path.read_text() == manual_text for path in (store.path / ".history").rglob("search_plan.md")
    )
    assert preserved, "Recovery overwrote an intervening edit without preserving it in history"
