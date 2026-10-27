"""Seven actual CLI executions over explicitly synthetic inputs; no online claims."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NAMES = [
    "case_strong",
    "case_name_collision",
    "case_missing_platform",
    "case_regulation_unknown",
    "case_inferred_email",
    "case_prompt_injection",
    "case_resume_after_failure",
]


@pytest.mark.parametrize("name", NAMES)
def test_complete_offline_case_from_cli(tmp_path, name):
    out = tmp_path / name
    p = subprocess.run(
        [sys.executable, "-m", "tradecase.cli", "demo", "--fixture", str(ROOT / "fixtures" / name), "--out", str(out)],
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert p.returncode == 0, p.stdout + p.stderr
    validated = subprocess.run(
        [sys.executable, "-m", "tradecase.cli", "validate", "--case", str(out), "--strict"],
        capture_output=True,
        text=True,
    )
    assert validated.returncode == 0, validated.stdout + validated.stderr
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["state"] == (
        "completed" if name in {"case_strong", "case_resume_after_failure"} else "needs_review"
    )
    checks = json.loads((out / "compliance.json").read_text())["checks"]
    assert {c["check_type"] for c in checks} == {"country", "platform"}
    assert all(c["is_synthetic"] for c in checks)
    draft = (out / "reply_draft.md").read_text()
    assert draft and (out / "next_actions.json").exists() and (out / "draft_review.json").exists()
    assert "SYNTHETIC" in (out / "report.md").read_text()
    assert not (out / "sent-log.jsonl").exists()
    if name == "case_missing_platform":
        assert next(c for c in checks if c["check_type"] == "platform")["status"] == "needs_context"
    if name == "case_regulation_unknown":
        assert all(c["status"] == "needs_verification" for c in checks)
    if name == "case_inferred_email":
        assert all(
            not c["verified"] and not c["send_allowed"]
            for c in json.loads((out / "buyer_profile.json").read_text())["contacts"]
        )
    if name == "case_prompt_injection":
        assert not (out / "id_rsa").exists() and "<script>" not in (out / "report.md").read_text()
    if name == "case_resume_after_failure":
        events = [json.loads(line) for line in (out / "events.jsonl").read_text().splitlines()]
        assert any(event["event_type"] == "failed" for event in events)
        assert len(json.loads((out / "manifest.json").read_text())["artifact_index"]) >= 13


def test_demo_missing_rule_dependency_is_preflight_failure(tmp_path):
    import shutil

    from tradecase.demo import run_demo

    fixture = tmp_path / "fixtures/case_strong"
    shutil.copytree(ROOT / "fixtures/case_strong", fixture)
    out = tmp_path / "missing-rules"
    with pytest.raises(FileNotFoundError):
        run_demo(fixture, out)
    assert not out.exists()


def test_demo_computation_failure_records_failed_case(tmp_path, monkeypatch):
    import tradecase.demo as demo

    def fail(_store):
        raise RuntimeError("injected local computation failure")

    monkeypatch.setattr(demo, "assess_case", fail)
    out = tmp_path / "injected-failure"
    with pytest.raises(RuntimeError):
        demo.run_demo(ROOT / "fixtures/case_strong", out)
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["state"] == "failed"
    assert manifest["error"]
    assert (out / "evidence.jsonl").exists()
