"""Noninteractive deterministic CLI. No model loop and no sending command."""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import sys
from pathlib import Path

from pydantic import ValidationError

from tradecase import __version__
from tradecase.case_store import CaseStore
from tradecase.ingestion import parse_inquiry, parse_seller
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
    init.add_argument("--synthetic", action="store_true", default=None)
    init.add_argument("--out", required=True, type=Path)
    for name in ["validate", "status", "recover", "assess", "report", "draft", "compliance"]:
        item = commands.add_parser(name)
        item.add_argument("--case", required=True, type=Path)
        if name == "validate":
            item.add_argument("--strict", action="store_true")
        if name == "compliance":
            item.add_argument("--rules", required=True, type=Path)
    put = commands.add_parser("put", help="Import an Agent-authored artifact through schema validation")
    put.add_argument("--case", required=True, type=Path)
    put.add_argument("--artifact", required=True)
    put.add_argument("--file", required=True, type=Path)
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
    elif args.command == "compliance":
        from tradecase.compliance import check_case

        check_case(store, args.rules)
    elif args.command == "draft":
        from tradecase.reporting import draft_case

        draft_case(store)
    elif args.command == "report":
        from tradecase.reporting import report_case

        report_case(store)
    emit(store.read("manifest.json"))
    return 0


def main():
    args = build_parser().parse_args()
    try:
        return dispatch(args)
    except (ValueError, OSError, ValidationError, ImportError) as exc:
        emit({"error": str(exc), "command": args.command, "status": "failed"})
        return 2


if __name__ == "__main__":
    sys.exit(main())
