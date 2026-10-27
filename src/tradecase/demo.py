"""Reproducible offline assembly of labelled synthetic Cases; no Agent or network."""

from __future__ import annotations

import base64
import copy
import json
import time
from pathlib import Path

from tradecase.assessment import assess_case
from tradecase.buyer_research import research_from_local
from tradecase.case_store import CaseStore
from tradecase.compliance import check_case
from tradecase.models import CaseInput, Evidence
from tradecase.reporting import draft_case, report_case
from tradecase.util import digest, json_bytes, no_symlinks
from tradecase.validation import validate_case

FIXTURE_CLOCK = "2026-10-27T12:00:00Z"


def run_demo(fixture: Path, out: Path) -> dict:
    started = time.monotonic()
    fixture = Path(fixture).absolute()
    no_symlinks(fixture)
    path = fixture / "fixture.json"
    no_symlinks(path)
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("fixture exceeds 2 MiB")
    data = json.loads(path.read_text("utf-8"))
    if data.get("is_synthetic") is not True or data["inquiry"].get("is_synthetic") is not True:
        raise ValueError("demo accepts explicitly synthetic fixtures only")
    raw = json_bytes(data["inquiry"])
    inquiry = CaseInput.model_validate(
        {
            **data["inquiry"],
            "case_id": Path(out).name,
            "received_at": FIXTURE_CLOCK,
            "raw_content": raw.decode(),
            "raw_sha256": digest(raw),
            "raw_bytes_base64": base64.b64encode(raw).decode(),
        }
    )
    rules_path = fixture.parent.parent / "rules/synthetic-demo-v1.json"
    no_symlinks(rules_path)
    rules = json.loads(rules_path.read_text("utf-8"))
    store = CaseStore.create(out, inquiry, data["seller"])
    try:
        store.transition(
            "running",
            "offline_research",
            detail={
                "mode": "synthetic_offline",
                "fixture": fixture.name,
                "network_calls": 0,
                "model_calls": 0,
                "fixture_sha256": digest(path.read_bytes()),
            },
        )
        for name, text in data["snapshots"].items():
            store.save_snapshot("snapshots/" + name, text)
        evidence = copy.deepcopy(data["evidence"])
        observations = research_from_local(
            inquiry.model_dump(mode="json"),
            evidence,
            [
                {
                    "source_url": "https://harbor-toys.invalid/about",
                    "text": data["snapshots"]["buyer.txt"],
                    "evidence_ids": ["ev-contact"],
                }
            ],
        )
        store.save_snapshot("snapshots/extraction.json", json.dumps(observations, ensure_ascii=False, indent=2))
        store.write(
            "search_plan.md",
            "SYNTHETIC / OFFLINE: load supplied research observations, retain entity boundaries, "
            "validate evidence, apply fixed scoring and scoped demo rules. No network or model call occurs.\n",
        )
        store.write("candidates.jsonl", data["candidates"])
        store.write("buyer_profile.json", {**data["profile"], "case_id": inquiry.case_id})
        if data.get("rule_scenario") == "expired_synthetic":
            for rule in rules["rules"]:
                rule["valid_until"] = "2026-10-26T12:00:00Z"
                rule["source_current"] = False
        for rule in rules["rules"]:
            eid = rule["source_evidence_ids"][0]
            snapshot = "snapshots/" + eid + ".txt"
            text = "SYNTHETIC RULE FOR OFFLINE ENGINE TEST ONLY\n" + rule["rationale"]
            store.save_snapshot(snapshot, text)
            evidence.append(
                Evidence(
                    evidence_id=eid,
                    claim=rule["rationale"],
                    source_url=rule["source_url"],
                    source_type="government" if rule["check_type"] == "country" else "platform_official",
                    source_title="SYNTHETIC rule fixture, not actual law",
                    captured_at=FIXTURE_CLOCK,
                    excerpt=rule["rationale"],
                    retrieved_by="synthetic offline fixture",
                    assertion_status="supported",
                    confidence_label="medium",
                    is_synthetic=True,
                    local_snapshot_ref=snapshot,
                ).model_dump(mode="json")
            )
        store.write("evidence.jsonl", evidence)
        if data.get("simulate_failure"):
            store.transition("failed", "research", error="SYNTHETIC offline simulated source interruption")
            # New store instance demonstrates session-independent resume; I/O-tear
            # recovery is separately exercised by the actual fault-injection test.
            store = CaseStore(store.path)
            store.recover()
            store.transition(
                "running", "research_resumed", detail={"simulation": True, "retained_evidence": len(evidence)}
            )
        store.write("assessment.json", {"case_id": inquiry.case_id, "signals": data["signals"], "is_synthetic": True})
        assess_case(store)
        store.save_snapshot("snapshots/rule-input.json", json.dumps(rules, ensure_ascii=False, indent=2))
        check_case(store, store.path / "snapshots/rule-input.json", checked_at=FIXTURE_CLOCK)
        draft_case(store)
        report_case(store)
        errors = validate_case(store.path, strict=True)
        if errors:
            store.transition("failed", "validation", error="; ".join(errors))
            raise ValueError("; ".join(errors))
        assessment = store.read("assessment.json")
        checks = store.read("compliance.json")["checks"]
        blockers = list(assessment["reason_codes"]) + [
            c["check_id"] + ":" + c["status"] for c in checks if c["status"] not in {"pass", "not_applicable"}
        ]
        state = "needs_review" if blockers else "completed"
        store.transition(state, "deliverables", blockers=blockers)
        store.record(
            "offline_demo_finished",
            {
                "mode": "synthetic_offline",
                "network_calls": 0,
                "model_calls": 0,
                "email_sends": 0,
                "estimated_external_cost_usd": 0,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "evidence_count": len(evidence),
                "evidence_coverage": assessment["evidence_coverage"],
                "unresolved_risks": len(blockers),
                "human_review_error_count": None,
                "human_review_error_count_note": "not measured; this is not an accuracy benchmark",
            },
        )
        final_errors = validate_case(store.path, strict=True)
        if final_errors:
            raise ValueError("; ".join(final_errors))
        return {
            "case": str(store.path),
            "state": state,
            "valid": True,
            "mode": "synthetic_offline",
            "network_calls": 0,
            "email_sends": 0,
            "report": str(store.path / "report.md"),
        }
    except Exception as exc:
        # Preserve the original failure and all prior evidence. An unfinished
        # I/O transaction must be recovered explicitly, never overwritten here.
        try:
            if not (store.path / ".transaction.json").exists():
                manifest = store.read("manifest.json")
                if manifest["state"] not in {"completed", "cancelled"}:
                    store.transition(
                        "failed", "offline_demo", error=f"Offline demonstration failed: {type(exc).__name__}"
                    )
        except (OSError, ValueError):
            pass
        raise
