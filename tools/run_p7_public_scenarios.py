"""Run constructed business questions against captured real public sources.

Sources are actual host-tool captures; questions/product attributes are explicit
synthetic test inputs, not customer inquiries or real product representations.
This runner does not fetch network pages or call a model.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from tradecase.assessment import assess_case
from tradecase.buyer_research import research_from_local
from tradecase.case_store import CaseStore
from tradecase.compliance import check_case
from tradecase.models import Evidence
from tradecase.reporting import draft_case, report_case
from tradecase.util import utc_now
from tradecase.validation import validate_case

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = ROOT / "docs/evidence/P7"
SCENARIOS = [
    {
        "id": "ikea-entity-ambiguity",
        "hint": "IKEA",
        "website": "https://www.ikea.com",
        "question": "Resolve IKEA brand, retailer and franchisor legal entity before assuming a buyer.",
        "attrs": {},
        "platform": None,
    },
    {
        "id": "ul-evidence-insufficient",
        "hint": "UL Solutions",
        "website": "https://www.ul.com",
        "question": "Does the public website establish this company has purchasing intent for our products?",
        "attrs": {},
        "platform": None,
    },
    {
        "id": "dynamic-public-page",
        "hint": None,
        "website": None,
        "question": "Can a dynamic public page be rendered and does it establish a buyer relationship?",
        "attrs": {},
        "platform": None,
    },
    {
        "id": "children-label-conflict",
        "hint": "IKEA",
        "website": "https://www.ikea.com",
        "question": "Hypothetical children product has no tracking label; identify the official guidance conflict.",
        "attrs": {"children_product": True, "tracking_label_present": False},
        "platform": "amazon_us",
    },
    {
        "id": "amazon-missing-context",
        "hint": None,
        "website": None,
        "question": "Can an Amazon US product listing be declared compliant without actual category and safety documents?",
        "attrs": {},
        "platform": "amazon_us",
    },
]


def main(out_root: Path):
    captured = json.loads((EVIDENCE_DIR / "host-web-sources.json").read_text())
    amazon = json.loads((EVIDENCE_DIR / "amazon-safety-source.json").read_text())
    dynamic = json.loads((EVIDENCE_DIR / "web-access-independent.json").read_text())
    original = captured["result"]
    specifications = [
        (
            "p7-ikea",
            "IKEA describes its franchisor and franchise system.",
            "https://www.ikea.com/global/en/our-business/how-we-work/the-ikea-franchise-system/",
            "official_site",
            "Inter IKEA Systems B.V. is the owner of the IKEA Concept and worldwide IKEA franchisor.",
            "host-web.json",
            original,
        ),
        (
            "p7-ul",
            "UL describes services for retail and consumer products.",
            "https://www.ul.com/about",
            "official_site",
            "Helping the retail and consumer products industry deliver safer, higher-quality and more sustainable products",
            "host-web.json",
            original,
        ),
        (
            "live-cpsc-tracking-guidance",
            "CPSC describes tracking marks for children products and packaging.",
            "https://www.cpsc.gov/FAQ/Tracking-Label",
            "government",
            "Are permanently affixed to the product and its packaging, to the extent practicable",
            "host-web.json",
            original,
        ),
        (
            "live-amazon-listing-safety",
            "Amazon says listing safety information depends on the product.",
            "https://sell.amazon.com/blog/amazon-product-listings",
            "platform_official",
            "The information you share in this tab will depend on your product.",
            "amazon-web.json",
            amazon["result"],
        ),
    ]
    rows = []
    for eid, claim, url, kind, excerpt, snapshot, source_text in specifications:
        assert excerpt in source_text, (eid, "excerpt not in captured source text")
        rows.append(
            Evidence(
                evidence_id=eid,
                claim=claim,
                source_url=url,
                source_type=kind,
                captured_at=captured["captured_at"] if snapshot == "host-web.json" else amazon["captured_at"],
                excerpt=excerpt,
                retrieved_by="host web open; captured text, not raw response",
                assertion_status="supported",
                confidence_label="medium",
                is_synthetic=False,
                local_snapshot_ref="snapshots/" + snapshot,
            ).model_dump(mode="json")
        )
    observed = json.loads(next(x["response"]["value"] for x in dynamic["calls"] if x["path"] == "/eval"))
    assert observed["quotes"] == 10 and observed["authors"] == 10
    rows.append(
        Evidence(
            evidence_id="p7-dynamic",
            claim="Isolated browser rendered ten quote and author elements.",
            source_url=observed["url"],
            source_type="other",
            captured_at=dynamic["captured_at"],
            locator="Web Access /eval response in indexed snapshot",
            retrieved_by="isolated Web Access + Chrome",
            assertion_status="supported",
            confidence_label="medium",
            is_synthetic=False,
            local_snapshot_ref="snapshots/browser-observation.json",
        ).model_dump(mode="json")
    )
    summaries = []
    for scenario in SCENARIOS:
        start = time.monotonic()
        out = out_root / scenario["id"]
        inquiry = {
            "case_id": scenario["id"],
            "received_at": utc_now(),
            "buyer_message": "SYNTHETIC P7 analyst test question, not a customer inquiry: " + scenario["question"],
            "buyer_company_hint": scenario["hint"],
            "buyer_website_hint": scenario["website"],
            "target_country": "US",
            "platform": scenario["platform"],
            "product_summary": "Hypothetical product attributes for test only; no actual seller product supplied",
            "is_synthetic": True,
        }
        seller = {
            "product_summary": "Hypothetical scenario only",
            "product_attributes": scenario["attrs"],
            "is_synthetic": True,
        }
        store = CaseStore.create(out, inquiry, seller)
        store.transition("running", "public_source_import")
        for snapshot, source in [
            ("host-web.json", captured),
            ("amazon-web.json", amazon),
            ("browser-observation.json", dynamic),
        ]:
            store.save_snapshot("snapshots/" + snapshot, json.dumps(source, ensure_ascii=False, indent=2))
        store.write("evidence.jsonl", rows)
        store.write(
            "search_plan.md",
            "Actual host-captured public sources; analyst questions and product attributes "
            "are synthetic. No customer inquiry, source re-fetch, external action, or model call.\n",
        )
        pages = []
        if scenario["id"] == "ikea-entity-ambiguity":
            pages = [{"source_url": specifications[0][2], "text": specifications[0][4], "evidence_ids": ["p7-ikea"]}]
        elif scenario["id"] == "ul-evidence-insufficient":
            pages = [{"source_url": specifications[1][2], "text": specifications[1][4], "evidence_ids": ["p7-ul"]}]
        research = research_from_local(store.read("input.json"), rows, pages)
        if scenario["id"] == "ikea-entity-ambiguity":
            research["candidates"].append(
                {
                    "candidate_id": "inter-ikea-systems",
                    "name": "Inter IKEA Systems B.V.",
                    "website": "https://www.inter.ikea.com",
                    "domain": "inter.ikea.com",
                    "identity_status": "unverified",
                    "evidence_ids": ["p7-ikea"],
                    "is_synthetic": True,
                }
            )
            research["profile"]["candidate_ids"].append("inter-ikea-systems")
            research["profile"]["unresolved_items"].append(
                "Brand, franchisor and retail operator may be distinct; "
                "identify the contracting entity before following up."
            )
        store.write("candidates.jsonl", research["candidates"])
        store.write("buyer_profile.json", research["profile"])
        store.write("assessment.json", {"case_id": scenario["id"], "signals": {}, "is_synthetic": True})
        assessment = assess_case(store)
        checks = check_case(store, ROOT / "rules/live-research-2026-10-27.json")["checks"]
        draft_case(store)
        report_case(store)
        errors = validate_case(store.path, strict=True)
        if errors:
            raise ValueError(scenario["id"] + ": " + "; ".join(errors))
        assert assessment["decision"] == "needs_review"
        assert not any(c["status"] == "pass" for c in checks)
        if scenario["id"] == "ikea-entity-ambiguity":
            assert len(research["candidates"]) == 2 and research["profile"]["selected_candidate_id"] is None
        if scenario["id"] == "children-label-conflict":
            assert next(c for c in checks if c["check_type"] == "country")["status"] == "needs_verification"
        if scenario["id"] == "amazon-missing-context":
            assert next(c for c in checks if c["check_type"] == "platform")["status"] == "needs_context"
        store.record(
            "p7_public_source_scenario",
            {
                "source_mode": "previously captured actual public source",
                "input_mode": "synthetic analyst question, not customer inquiry",
                "new_network_calls": 0,
                "new_model_calls": 0,
                "email_sends": 0,
            },
        )
        assert not validate_case(store.path, strict=True)
        (EVIDENCE_DIR / (scenario["id"] + "-report.md")).write_text((out / "report.md").read_text())
        summaries.append(
            {
                "case_id": scenario["id"],
                "case_path": str(out.relative_to(ROOT)),
                "test_question": scenario["question"],
                "input_synthetic": True,
                "public_sources_synthetic": False,
                "candidate_count": len(research["candidates"]),
                "selected_candidate_id": research["profile"]["selected_candidate_id"],
                "assessment": assessment["decision"],
                "score": assessment["score"],
                "checks": checks,
                "state": store.read("manifest.json")["state"],
                "strict_valid": True,
                "evidence_ids": [row["evidence_id"] for row in rows],
                "failure_or_review_reasons": assessment["reason_codes"],
                "unresolved_items": research["profile"]["unresolved_items"],
                "source_capture_refs": [
                    "docs/evidence/P7/host-web-sources.json",
                    "docs/evidence/P7/amazon-safety-source.json",
                    "docs/evidence/P7/web-access-independent.json",
                ],
                "elapsed_case_seconds": round(time.monotonic() - start, 3),
                "case_new_model_calls": 0,
                "case_new_model_cost_usd": 0,
                "shared_host_model_usage_tokens": None,
                "shared_host_model_cost_usd": None,
                "human_accuracy_review": "not independently measured",
            }
        )
    (EVIDENCE_DIR / "scenario-results.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "cases": len(summaries),
                "strict_valid": True,
                "all_needs_review": all(s["state"] == "needs_review" for s in summaries),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-root", type=Path, default=ROOT / "cases/p7")
    args = parser.parse_args()
    main(args.out_root.absolute())
