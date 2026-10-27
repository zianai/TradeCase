import json
from pathlib import Path

from tradecase.case_store import CaseStore
from tradecase.reporting import report_case


def test_partial_report_states_missing_checks_without_inventing_pass(tmp_path):
    store = CaseStore.create(
        tmp_path / "case",
        {
            "case_id": "report",
            "received_at": "2026-10-27T12:00:00Z",
            "buyer_message": "Untrusted <script>alert(1)</script>",
            "is_synthetic": True,
        },
        {"is_synthetic": True},
    )
    report_case(store)
    text = store.read("report.md")
    assert "Country and platform checks have not been supplied" in text
    assert "<script>" not in text and "&lt;script&gt;" in text


def test_two_risk_feedback_forms(tmp_path):
    from tradecase.compliance import check_case

    root = Path(__file__).resolve().parents[2]
    store = CaseStore.create(
        tmp_path / "case",
        {
            "case_id": "report",
            "received_at": "2026-10-27T12:00:00Z",
            "buyer_message": "Synthetic research",
            "target_country": "US",
            "is_synthetic": True,
        },
        {"product_attributes": {"children_product": True}, "is_synthetic": True},
    )
    check_case(store, root / "rules/synthetic-demo-v1.json", checked_at="2026-10-27T12:00:00Z")
    report_case(store)
    checks = store.read("compliance.json")["checks"]
    assert {c["check_type"] for c in checks} == {"country", "platform"}
    assert all(c["status"] != "pass" and c["severity"] for c in checks)
    text = store.read("report.md")
    assert "country:" in text and "platform:" in text and "Annotation:" in text and "Next step:" in text
    assert json.loads((store.path / "compliance.json").read_text())["checks"] == checks
