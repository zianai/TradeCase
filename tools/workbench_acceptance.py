"""Reproducible seven-scenario platform run; wholly synthetic, no model/network/send."""

from __future__ import annotations

import asyncio
import json
import math
import statistics
import tempfile
import time
from pathlib import Path

from tradecase.platform.config import Settings
from tradecase.platform.contracts import CreateCase
from tradecase.platform.coordinator import CaseRunCoordinator
from tradecase.platform.db import Database
from tradecase.platform.services import CaseService

SCENARIOS = [
    "case_strong",
    "case_name_collision",
    "case_missing_platform",
    "case_regulation_unknown",
    "case_inferred_email",
    "case_prompt_injection",
    "case_resume_after_failure",
]


def main():
    output = Path("docs/evidence/full-delivery/platform-scenarios.json")
    with tempfile.TemporaryDirectory(prefix="tradecase-acceptance-") as directory:
        root = Path(directory).resolve()
        settings = Settings(
            database_url="sqlite:///" + str(root / "db.sqlite"),
            storage_root=root / "objects",
            work_root=root / "work",
            checkpoint_url="sqlite:///" + str(root / "checkpoint.sqlite"),
            demo_enabled=True,
            queue_mode="inline",
        )
        settings.prepare()
        db = Database(settings.database_url)
        db.create_schema()
        service = CaseService(db, settings)
        _, token = service.provision("acceptance", "Synthetic reviewer")
        actor = service.authenticate(token)
        results = []
        for name in SCENARIOS:
            start = time.perf_counter()
            case = service.create(actor, CreateCase(title=name, fixture=name), name)
            coordinator = CaseRunCoordinator(service)
            workflow = coordinator.request(actor, case["id"])
            result = asyncio.run(coordinator.run(actor["tenant_id"], workflow["id"]))
            final = service.get(actor["tenant_id"], case["id"])
            assert result["status"] == "WAITING_HUMAN" and final["status"] == "NEEDS_REVIEW"
            ev = service.evidence(actor["tenant_id"], case["id"])
            results.append(
                {
                    "scenario": name,
                    "workflow_status": result["status"],
                    "case_status": final["status"],
                    "research_status": final["research_status"],
                    "coverage": final["assessment"]["evidence_coverage"],
                    "claims": len(ev["claims"]),
                    "source_snapshots": len(ev["sources"]),
                    "elapsed_seconds": round(time.perf_counter() - start, 4),
                    "synthetic": True,
                }
            )
        values = sorted(row["elapsed_seconds"] for row in results)
        evidence = {
            "mode": "synthetic_offline_sqlite",
            "samples": len(results),
            "model_calls": 0,
            "network_calls": 0,
            "real_email_sends": 0,
            "timing_definition": "create through persisted approval interrupt; no human wait, not production latency",
            "median_seconds": statistics.median(values),
            "p95_nearest_rank_seconds": values[math.ceil(0.95 * len(values)) - 1],
            "scenarios": results,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(evidence, indent=2))
        print(json.dumps(evidence, indent=2))
        db.close()


if __name__ == "__main__":
    main()
