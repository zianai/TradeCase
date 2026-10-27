"""Evaluate five actual public UNICEF notices with no contact or submission.

Input is a deliberately limited, contact-redacted page excerpt, not a private
customer inquiry. Seller capability and current country law remain unknown.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import time
from pathlib import Path

from tradecase.assessment import assess_case
from tradecase.buyer_research import research_from_local
from tradecase.case_store import CaseStore
from tradecase.compliance import check_case
from tradecase.models import Evidence
from tradecase.reporting import draft_case, report_case
from tradecase.validation import validate_case

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/P7"
COUNTRIES = {"318181": "UA", "301686": "JO", "299179": "MY", "290489": "EC", "310066": "PS"}
DEADLINES = {
    "318181": "2026-10-20",
    "301686": "2026-06-11",
    "299179": "2026-05-21",
    "290489": "2026-02-12",
    "310066": "2026-08-30",
}


def main(out_root: Path):
    sources = json.loads((EVIDENCE / "public-procurement-sources.json").read_text())
    host = json.loads((EVIDENCE / "host-web-sources.json").read_text())
    amazon = json.loads((EVIDENCE / "amazon-safety-source.json").read_text())
    rule_evidence = []
    for eid, url, kind, excerpt, captured, snapshot in [
        (
            "live-cpsc-tracking-guidance",
            "https://www.cpsc.gov/FAQ/Tracking-Label",
            "government",
            "Are permanently affixed to the product and its packaging, to the extent practicable",
            host,
            "host-web.json",
        ),
        (
            "live-amazon-listing-safety",
            "https://sell.amazon.com/blog/amazon-product-listings",
            "platform_official",
            "The information you share in this tab will depend on your product.",
            amazon,
            "amazon-web.json",
        ),
    ]:
        if excerpt not in captured["result"]:
            raise ValueError("official source excerpt not present in captured text: " + eid)
        rule_evidence.append(
            Evidence(
                evidence_id=eid,
                claim="Official public guidance excerpt",
                source_url=url,
                source_type=kind,
                captured_at=captured["captured_at"],
                excerpt=excerpt,
                retrieved_by="host web open; captured text, not raw response",
                assertion_status="supported",
                confidence_label="medium",
                is_synthetic=False,
                local_snapshot_ref="snapshots/" + snapshot,
            ).model_dump(mode="json")
        )
    results = []
    for source in sources:
        start = time.monotonic()
        notice_id = source["source_url"].rsplit("/", 1)[1]
        case_id = "unicef-" + notice_id
        title = source["selected_lines"].splitlines()[0].removeprefix("L19: # ").strip()
        raw = source["selected_lines"].encode()
        inquiry = {
            "case_id": case_id,
            "received_at": source["captured_at"],
            "buyer_message": raw.decode(),
            "buyer_company_hint": "UNICEF",
            "target_country": COUNTRIES[notice_id],
            "product_summary": title,
            "is_synthetic": False,
            "raw_content": raw.decode(),
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "raw_bytes_base64": base64.b64encode(raw).decode(),
            "parsing_warnings": [
                "Public procurement notice excerpt; not a direct inquiry to the seller; "
                "contact sections and attachments not captured."
            ],
            "user_constraints": [
                "Public notice deadline "
                + DEADLINES[notice_id]
                + " has passed as of capture; do not submit or contact."
            ],
        }
        store = CaseStore.create(out_root / case_id, inquiry, {"is_synthetic": False})
        store.transition("running", "public_source_import")
        store.save_snapshot("snapshots/procurement.json", json.dumps(source, ensure_ascii=False, indent=2))
        for name, content in [("host-web.json", host), ("amazon-web.json", amazon)]:
            store.save_snapshot("snapshots/" + name, json.dumps(content, ensure_ascii=False, indent=2))
        source_id = "p7-public-" + notice_id
        evidence = Evidence(
            evidence_id=source_id,
            claim="UNGM publishes a UNICEF procurement notice.",
            source_url=source["source_url"],
            source_type="official_site",
            source_title=title,
            captured_at=source["captured_at"],
            excerpt=title,
            retrieved_by=source["retrieved_by"],
            assertion_status="supported",
            confidence_label="medium",
            is_synthetic=False,
            local_snapshot_ref="snapshots/procurement.json",
        ).model_dump(mode="json")
        rows = [evidence, *rule_evidence]
        store.write("evidence.jsonl", rows)
        store.write(
            "search_plan.md",
            "Public UNGM procurement notice, not an individual buyer inquiry. "
            "Actual seller credentials, complete tender attachments and relevant local rules are absent. "
            "Notice deadline has passed. No contact or submission is allowed.\n",
        )
        research = research_from_local(store.read("input.json"), rows)
        store.write("candidates.jsonl", research["candidates"])
        store.write("buyer_profile.json", research["profile"])
        store.write("assessment.json", {"case_id": case_id, "signals": {}, "is_synthetic": False})
        assessment = assess_case(store)
        checks = check_case(store, ROOT / "rules/live-research-2026-10-27.json")["checks"]
        draft_case(store)
        report_case(store)
        errors = validate_case(store.path, strict=True)
        if errors:
            raise ValueError(case_id + ": " + "; ".join(errors))
        assert assessment["decision"] == "needs_review" and assessment["score"] is None
        assert any(c["check_type"] == "country" and c["status"] == "needs_verification" for c in checks)
        store.record(
            "p7_public_procurement",
            {
                "source_url": source["source_url"],
                "deadline": DEADLINES[notice_id],
                "expired_at_capture": True,
                "direct_customer_inquiry": False,
                "network_calls_for_case_build": 0,
                "model_calls_for_case_build": 0,
                "email_sends": 0,
            },
        )
        assert not validate_case(store.path, strict=True)
        (EVIDENCE / (case_id + "-report.md")).write_text((store.path / "report.md").read_text())
        results.append(
            {
                "case_id": case_id,
                "case_path": str(store.path.relative_to(ROOT)),
                "source_url": source["source_url"],
                "source_evidence_id": source_id,
                "deadline": DEADLINES[notice_id],
                "expired_at_capture": True,
                "real_public_procurement_notice": True,
                "not_a_direct_customer_inquiry": True,
                "status": store.read("manifest.json")["state"],
                "strict_valid": True,
                "assessment": assessment["decision"],
                "score": assessment["score"],
                "reason_codes": assessment["reason_codes"],
                "checks": checks,
                "source_capture_seconds": round(source["duration_ms"] / 1000, 3),
                "elapsed_case_seconds": round(time.monotonic() - start, 3),
                "model_tokens": None,
                "model_cost_usd": None,
                "case_build_model_calls": 0,
                "case_build_model_cost_usd": 0,
                "attachment_review": "not performed",
                "seller_eligibility": "unknown",
                "case_source_excerpt_not_full_notice": True,
            }
        )
    (EVIDENCE / "public-procurement-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "real_public_notices": len(results),
                "strict_valid": True,
                "all_expired_and_need_review": all(
                    r["expired_at_capture"] and r["status"] == "needs_review" for r in results
                ),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-root", type=Path, default=ROOT / "cases/p7-public")
    args = parser.parse_args()
    main(args.out_root.absolute())
