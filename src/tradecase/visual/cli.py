"""HTTP client for the Visual Domain; no separate business or generation loop."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx


def main(argv=None):
    parser = argparse.ArgumentParser(prog="tradecase visual")
    parser.add_argument("--url", default=os.getenv("TRADECASE_API_URL", "http://127.0.0.1:8800"))
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--idempotency-key", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ["suggest", "list", "create", "plan", "import-products"]:
        p = sub.add_parser(name)
        p.add_argument("--case", required=True)
        if name in ["create", "plan"]:
            p.add_argument("--plan", required=True, type=Path)
        if name == "import-products":
            p.add_argument("--file", required=True, type=Path)
    for name in ["status", "approve-plan", "sync", "cancel", "review", "revise", "attach"]:
        p = sub.add_parser(name)
        p.add_argument("task_id")
        if name != "status":
            p.add_argument("--file", required=True, type=Path, help="Version-bound JSON request")
    p = sub.add_parser("export")
    p.add_argument("proposal_id")
    p.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    # Credentials are sent only to the explicitly configured origin, never redirects.
    parsed = httpx.URL(args.url)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.host in {"localhost", "127.0.0.1", "::1"}):
        parser.error("Use HTTPS, or HTTP on loopback only")
    headers = {
        "Authorization": "Bearer " + Path(args.token_file).read_text().strip(),
        "Idempotency-Key": args.idempotency_key or uuid4().hex,
    }
    try:
        with httpx.Client(base_url=args.url, headers=headers, timeout=45, follow_redirects=False, trust_env=False) as c:
            if args.command in ["suggest", "list"]:
                r = c.get(f"/api/cases/{args.case}/visuals")
            elif args.command in ["plan", "create"]:
                r = c.post(f"/api/cases/{args.case}/visuals/tasks", json=json.loads(args.plan.read_text()))
            elif args.command == "import-products":
                if args.file.suffix.lower() == ".csv":
                    rows = list(csv.DictReader(args.file.read_text().splitlines()))
                    for row in rows:
                        for key in ["colors", "structure", "customization"]:
                            if key in row:
                                row[key] = [x.strip() for x in row[key].split("|") if x.strip()]
                        if "external_use" in row:
                            row["external_use"] = row["external_use"].lower() == "true"
                        if row.get("expected_version"):
                            row["expected_version"] = int(row["expected_version"])
                        else:
                            row.pop("expected_version", None)
                else:
                    rows = json.loads(args.file.read_text())
                    rows = rows if isinstance(rows, list) else [rows]
                results = []
                for i, row in enumerate(rows):
                    r = c.post(
                        f"/api/cases/{args.case}/visuals/products",
                        json=row,
                        headers={"Idempotency-Key": headers["Idempotency-Key"] + ":" + str(i)},
                    )
                    r.raise_for_status()
                    results.append(r.json())
                print(json.dumps(results, ensure_ascii=False, indent=2))
                return 0
            elif args.command == "export":
                if args.out.exists():
                    raise ValueError("Export destination already exists")
                r = c.get(f"/api/visual-proposals/{args.proposal_id}/export")
                r.raise_for_status()
                with args.out.open("xb") as f:
                    f.write(r.content)
                print(json.dumps({"saved": str(args.out), "bytes": len(r.content)}))
                return 0
            elif args.command == "status":
                r = c.get("/api/visual-tasks/" + args.task_id)
            else:
                action = {"review": "reviews", "revise": "revisions"}.get(args.command, args.command)
                r = c.post(
                    "/api/visual-tasks/" + args.task_id + "/" + action,
                    json=json.loads(args.file.read_text()) if hasattr(args, "file") else {},
                )
            r.raise_for_status()
            data = r.json()
            if args.command == "suggest":
                data = data["suggestions"]
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0
    except httpx.HTTPStatusError as exc:
        print(json.dumps({"status": "failed", "http_status": exc.response.status_code}))
        return 2
    except (httpx.RequestError, ValueError, OSError):
        print(json.dumps({"status": "failed", "error": "Visual API or input unavailable; no automatic retry"}))
        return 2
