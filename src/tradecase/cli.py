"""Noninteractive deterministic CLI. No model loop and no sending command."""

from __future__ import annotations

import argparse
import base64
import fcntl
import importlib.util
import json
import platform
import sys
from pathlib import Path

from pydantic import ValidationError

from tradecase import __version__
from tradecase.case_store import CaseStore
from tradecase.ingestion import parse_inquiry, parse_seller
from tradecase.util import digest, no_symlinks
from tradecase.validation import validate_case


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def build_parser():
    parser = argparse.ArgumentParser(prog="tradecase")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    init = commands.add_parser("init")
    init.add_argument("--inquiry", required=True, type=Path)
    init.add_argument("--seller", type=Path)
    init.add_argument("--target-country")
    init.add_argument("--platform")
    init.add_argument("--case-type", choices=["inquiry", "procurement"])
    init.add_argument("--deadline-evidence-id")
    init.add_argument("--synthetic", action="store_true", default=None)
    init.add_argument("--out", required=True, type=Path)
    for name in ["validate", "status", "recover", "assess", "report", "draft", "compliance"]:
        item = commands.add_parser(name)
        item.add_argument("--case", required=True, type=Path)
        if name == "validate":
            item.add_argument("--strict", action="store_true")
        if name == "compliance":
            item.add_argument("--rules", required=True, type=Path)
            item.add_argument(
                "--checked-at", help="Explicit historical clock for fully synthetic offline fixtures only"
            )
    put = commands.add_parser("put", help="Import an Agent-authored artifact through schema validation")
    put.add_argument("--case", required=True, type=Path)
    put.add_argument("--artifact", required=True)
    put.add_argument("--file", required=True, type=Path)
    research = commands.add_parser("research", help="Prepare unverified buyer candidates using local evidence")
    research.add_argument("--case", required=True, type=Path)
    research.add_argument("--pages", type=Path, help="Explicitly supplied public page observations JSON")
    capture = commands.add_parser("capture", help="Read one public URL as untrusted evidence; no browser")
    capture.add_argument("--case", required=True, type=Path)
    capture.add_argument("--url", required=True)
    search = commands.add_parser(
        "import-search", help="Normalize existing host search output without performing search"
    )
    search.add_argument("--case", required=True, type=Path)
    search.add_argument("--file", required=True, type=Path)
    search.add_argument("--query", required=True)
    search.add_argument("--captured-at", required=True)
    state = commands.add_parser("transition")
    state.add_argument("--case", required=True, type=Path)
    state.add_argument("--state", required=True)
    state.add_argument("--stage", required=True)
    state.add_argument("--error")
    demo = commands.add_parser("demo")
    demo.add_argument("--fixture", required=True, type=Path)
    demo.add_argument("--out", required=True, type=Path)
    install = commands.add_parser("install-skills")
    install.add_argument("--target", choices=["codex", "claude", "both"], default="both")
    install.add_argument("--scope", choices=["project"], default="project")
    install.add_argument("--project", type=Path, default=Path.cwd())
    return parser


def dispatch(args):
    if args.command == "doctor":
        emit(
            {
                "tradecase": __version__,
                "python": platform.python_version(),
                "core": "implemented",
                "network_required": False,
                "sending": "disabled",
                "agent_runtime": "host-owned",
                "crawl4ai_installed": importlib.util.find_spec("crawl4ai") is not None,
                "web_access": "blocked: root license unavailable; no automatic installation",
                "skills": {
                    k: (Path.cwd() / k / "skills/trade-inquiry/SKILL.md").is_file() for k in [".agents", ".claude"]
                },
            }
        )
        return 0
    if args.command == "init":
        seller = parse_seller(args.seller)
        inquiry = parse_inquiry(
            args.inquiry,
            args.out.name,
            target_country=args.target_country,
            platform=args.platform,
            case_type=args.case_type,
            deadline_evidence_id=args.deadline_evidence_id,
            is_synthetic=args.synthetic,
            product_summary=seller.product_summary,
        )
        store = CaseStore.create(args.out, inquiry, seller)
        emit(store.read("manifest.json"))
        return 0
    if args.command == "demo":
        from tradecase.demo import run_demo

        emit(run_demo(args.fixture, args.out))
        return 0
    if args.command == "install-skills":
        from tradecase.skill_install import install_skills

        emit(install_skills(args.project, args.target))
        return 0
    store = CaseStore(args.case)
    if args.command == "validate":
        errors = validate_case(args.case, strict=args.strict)
        emit({"valid": not errors, "strict": args.strict, "errors": errors})
        return 1 if errors else 0
    if args.command == "status":
        emit(
            {
                "manifest": store.read("manifest.json"),
                "validation_errors": validate_case(args.case),
                "remaining": validate_case(args.case, strict=True),
            }
        )
        return 0
    if args.command == "recover":
        emit(store.recover())
        return 0
    if args.command == "transition":
        store.transition(args.state, args.stage, error=args.error)
    elif args.command == "put":
        content = args.file.read_text("utf-8")
        if args.artifact.endswith(".jsonl"):
            data = [json.loads(line) for line in content.splitlines() if line.strip()]
        elif args.artifact.endswith(".json"):
            data = json.loads(content)
        else:
            data = content
        store.write(args.artifact, data)
    elif args.command == "assess":
        from tradecase.assessment import assess_case

        assess_case(store)
    elif args.command == "research":
        from tradecase.buyer_research import research_from_local

        rows = store.read("evidence.jsonl") if (store.path / "evidence.jsonl").exists() else []
        pages = json.loads(args.pages.read_text("utf-8")) if args.pages else None
        result = research_from_local(store.read("input.json"), rows, pages)
        store.write("candidates.jsonl", result["candidates"])
        if not (store.path / "evidence.jsonl").exists():
            store.write("evidence.jsonl", [])
        store.write("buyer_profile.json", result["profile"])
        store.record("research_prepared", {"candidates": len(result["candidates"]), "verification": "unverified"})
    elif args.command == "capture":
        return capture_url(store, args.url)
    elif args.command == "import-search":
        from tradecase.providers import normalize_host_search

        text = args.file.read_text("utf-8")
        try:
            value = json.loads(text)
            rows = value if isinstance(value, list) else value.get("results", [value])
        except json.JSONDecodeError:
            rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        result = normalize_host_search(rows, query=args.query, captured_at=args.captured_at)
        name = "snapshots/search-" + digest(text.encode())[:16] + ".json"
        store.save_snapshot(name, json.dumps(result, ensure_ascii=False, indent=2))
        store.record("search_imported", {"rows": len(result), "snapshot": name, "queries": 1})
    elif args.command == "compliance":
        from tradecase.compliance import check_case

        check_case(store, args.rules, checked_at=args.checked_at)
    elif args.command == "draft":
        from tradecase.reporting import draft_case

        draft_case(store)
    elif args.command == "report":
        from tradecase.reporting import report_case

        report_case(store)
    emit(store.read("manifest.json"))
    return 0


def capture_url(store, url):
    from tradecase.models import Evidence
    from tradecase.providers import ContentReader, ReadPolicy, ResearchBudget

    lock_path = store.path / ".network.lock"
    no_symlinks(lock_path)
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        manifest = store.read("manifest.json")
        if manifest["state"] in {"completed", "cancelled"}:
            raise ValueError("final Case requires explicit reopen before network research")
        budget = ResearchBudget.from_dict(manifest.get("runtime_metadata", {}).get("network_budget", {}))
        if budget.pages_used >= 15 or budget.requests_used >= 40:
            emit({"status": "blocked", "blockers": ["Case network budget exhausted"], "budget": budget.to_dict()})
            return 1
        request_cap = min(40, budget.requests_used + 8)
        reservation = {**budget.to_dict(), "pages_used": budget.pages_used + 1, "requests_used": request_cap}
        # Reserve the maximum this invocation can consume before any network I/O.
        # A killed process leaves its reservation consumed, never resets budget.
        store.record("public_read_reserved", {"request_limit": request_cap}, {"network_budget": reservation})
        result = ContentReader(policy=ReadPolicy(max_requests=request_cap), budget=budget).read(url)
        # Persist consumed attempts even on errors. No credential-bearing URL is logged.
        metadata = {"network_budget": budget.to_dict()}
        store.record(
            "public_read",
            {
                "status": result.status,
                "budget": budget.to_dict(),
                "blockers": result.blockers,
                "source": result.requested_url,
            },
            metadata,
        )
        payload = result.to_dict()
        if result.status == "fetched":
            identifier = "capture-" + digest((result.final_url + result.captured_at).encode())[:20]
            payload["raw_bytes_base64"] = base64.b64encode(result.raw_bytes).decode("ascii")
            store.save_snapshot(f"snapshots/{identifier}.json", json.dumps(payload, ensure_ascii=False, indent=2))
            store.save_snapshot(f"snapshots/{identifier}.txt", result.text)
            evidence = store.read("evidence.jsonl") if (store.path / "evidence.jsonl").exists() else []
            evidence.append(
                Evidence(
                    evidence_id=identifier,
                    claim="Retrieved public page; facts await host review.",
                    source_url=result.final_url,
                    source_type="other",
                    source_title=result.source_title,
                    captured_at=result.captured_at,
                    excerpt=result.text[:500],
                    retrieved_by=result.retrieved_by,
                    assertion_status="unverified",
                    confidence_label="low",
                    is_synthetic=result.is_synthetic,
                    local_snapshot_ref=f"snapshots/{identifier}.txt",
                ).model_dump(mode="json")
            )
            store.write("evidence.jsonl", evidence)
            emit(
                {
                    "status": result.status,
                    "evidence_id": identifier,
                    "snapshot": f"snapshots/{identifier}.json",
                    "budget": budget.to_dict(),
                    "assertion_status": "unverified",
                }
            )
            return 0
        # Do not echo unvalidated input URLs or remote data on a blocked read.
        emit({"status": result.status, "budget": budget.to_dict(), "blockers": result.blockers})
        return 1


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "visual":
        from tradecase.visual.cli import main as visual_main
        return visual_main(sys.argv[2:])
    args = build_parser().parse_args()
    try:
        return dispatch(args)
    except (ValueError, OSError, ValidationError, ImportError) as exc:
        emit({"error": str(exc), "command": args.command, "status": "failed"})
        return 2


if __name__ == "__main__":
    sys.exit(main())
