"""Import previously read public-source evidence; never pretend this is a customer inquiry."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from tradecase.case_store import CaseStore
from tradecase.models import Evidence
from tradecase.util import utc_now


def prepare(source: Path, output: Path):
    store = CaseStore.create(
        output,
        {
            "case_id": output.name,
            "received_at": utc_now(),
            "buyer_message": "Engineering research request, not a customer inquiry: inspect official public sources and identify missing product context.",
            "target_country": "US",
            "platform": "amazon_us",
            "product_summary": "No actual product specifications supplied",
            "is_synthetic": False,
        },
        {"product_summary": "No actual product specifications supplied", "is_synthetic": False},
    )
    rows = []
    for original in [json.loads(line) for line in (source / "evidence.jsonl").read_text().splitlines() if line]:
        raw = (source / original["local_snapshot_ref"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != original["snapshot_sha256"]:
            raise ValueError("Source audit snapshot hash differs from original capture")
        name = "snapshots/" + original["evidence_id"] + ".json"
        store.save_snapshot(
            name,
            json.dumps(
                {
                    "source_url": original["source_url"],
                    "captured_at": original["captured_at"],
                    "sha256": original["snapshot_sha256"],
                    "hash_basis": original["hash_basis"],
                    "raw_bytes_base64": base64.b64encode(raw).decode(),
                    "limitations": original["limitations"],
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        row = {key: value for key, value in original.items() if key in Evidence.model_fields}
        row["local_snapshot_ref"] = name
        rows.append(row)
    store.write("evidence.jsonl", rows)
    store.write(
        "search_plan.md",
        "Public official-source engineering check only. No buyer identity or purchasing intent conclusion.\n",
    )
    store.record(
        "host_sources_imported",
        {
            "count": len(rows),
            "retrieval_mode": "previously captured public sources",
            "is_synthetic": False,
            "limitations": "Not a live execution of the direct ContentReader or a real buyer inquiry",
        },
    )
    return store


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    case = prepare(args.source, args.out)
    print(
        json.dumps(
            {
                "case": str(case.path),
                "source_count": len(case.read("evidence.jsonl")),
                "status": "imported_real_capture",
            }
        )
    )
