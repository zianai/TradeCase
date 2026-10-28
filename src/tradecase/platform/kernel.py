"""Thin materialization of the retained deterministic business package.

The DB owns workbench facts; this CaseStore is a disposable compatibility view.
A signed source snapshot or an old report is never silently replaced by a model.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from tradecase.assessment import assess_case
from tradecase.buyer_research import research_from_local
from tradecase.case_store import CaseStore
from tradecase.compliance import check_case
from tradecase.demo import run_demo
from tradecase.models import SellerContext
from tradecase.platform.review_inputs import ReviewInputsService
from tradecase.reporting import draft_case, report_case


class BusinessKernel:
    def __init__(self, service):
        self.service = service

    def path(self, tenant, case_id, review_ref=None):
        # Both identities originate in trusted DB lookups, but still prohibit traversal.
        if any(not x or "/" in x or "\\" in x or x in {".", ".."} for x in (tenant, case_id)):
            raise ValueError("invalid materialization identity")
        if review_ref:
            if not review_ref.isalnum():
                raise ValueError("invalid review materialization identity")
            return self.service.settings.work_root / tenant / ("review-" + review_ref) / case_id
        return self.service.settings.work_root / tenant / case_id

    def materialize(self, tenant, case_id):
        case = self.service.get(tenant, case_id)
        review_ref = case["data"].get("review_inputs_ref")
        path = self.path(tenant, case_id, review_ref)
        if path.exists():
            store = CaseStore(path)
            if (store.path / ".transaction.json").exists():
                store.recover()
            return store
        path.parent.mkdir(parents=True, exist_ok=True)
        if review_ref:
            bundle = ReviewInputsService(self.service).bundle(tenant, case_id)
            # Publish an entirely validated immutable-version materialization atomically;
            # a killed process leaves no half-built directory that could be reused.
            with tempfile.TemporaryDirectory(prefix=".review-build-", dir=path.parent) as directory:
                built = Path(directory).resolve() / case_id
                store = CaseStore.create(built, bundle["inquiry"], bundle["seller_context"])
                store.transition("running", "reviewed_inputs")
                for name, metadata in bundle["snapshots"].items():
                    raw = self.service.storage.get(metadata["storage_ref"])
                    if not self.service.storage.verify(metadata["storage_ref"], metadata["sha256"]):
                        raise ValueError("review source snapshot integrity failure")
                    store.save_snapshot(name, raw.decode())
                for name, value in (
                    ("search_plan.md", "Use reviewer-bound existing evidence; investigate remaining gaps.\n"),
                    ("candidates.jsonl", bundle["candidates"]),
                    ("evidence.jsonl", bundle["evidence"]),
                    ("buyer_profile.json", bundle["profile"]),
                    ("assessment.json", bundle["assessment"]),
                    ("rules_snapshot.json", bundle["rules"]),
                    ("compliance.json", bundle["compliance"]),
                ):
                    store.write(name, value)
                store.save_snapshot("snapshots/platform-rules.json", json.dumps(bundle["rules"]))
                os.rename(built, path)
            return CaseStore(path)
        fixture = case["data"].get("fixture")
        if fixture:
            # Explicit synthetic adapter: reuse seven already-validated fixture pipelines.
            # This is labelled fixture materialization, never live model/source execution.
            run_demo(self.service.fixture_path(fixture), path)
            return CaseStore(path)
        store = CaseStore.create(path, case["inquiry"], SellerContext())
        store.transition("running", "platform_materialization")
        store.write("search_plan.md", "Research sources are unavailable until configured; no facts inferred.\n")
        prepared = research_from_local(case["inquiry"], [])
        store.write("candidates.jsonl", prepared["candidates"])
        store.write("evidence.jsonl", [])
        store.write(
            "buyer_profile.json",
            prepared["profile"],
        )
        store.write("assessment.json", {"case_id": case_id, "signals": {}, "is_synthetic": False})
        assess_case(store)
        return store

    def compute(self, tenant, case_id, stage):
        store = self.materialize(tenant, case_id)
        data = self.service.get(tenant, case_id)["data"]
        fixture = data.get("fixture") if not data.get("review_inputs_ref") else None
        if fixture:
            names = {
                "lead_qualification": "assessment.json",
                "compliance_checks": "compliance.json",
                "draft_response": "draft_review.json",
                "persist_report": "report.md",
            }
            return store.read(names[stage])
        if store.read("manifest.json")["state"] != "running":
            store.transition("running", stage)
        if stage == "lead_qualification":
            return assess_case(store)
        if stage == "compliance_checks":
            if not data.get("review_inputs_ref"):
                store.save_snapshot("snapshots/platform-rules.json", json.dumps({"rules": []}))
            return check_case(store, store.path / "snapshots/platform-rules.json")
        if stage == "draft_response":
            return draft_case(store)
        report_case(store)
        return store.read("report.md")
