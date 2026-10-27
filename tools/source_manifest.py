"""Record/check exact source lineage for inherited and adapted third-party files."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
B2B = "ac27d0ec6627366337423bfcb1ba86c5be5a95a5"
AI = "9b2fde8f719623c627516da2663707a893ee6805"
USED = {
    "contracts.py",
    "extract_contacts.py",
    "normalize_search_results.py",
    "dedupe_leads.py",
    "customs_verify.py",
    "evaluate_outreach_drafts.py",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build():
    original = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", B2B, "scripts"], cwd=ROOT, text=True
    ).splitlines()
    rows = []
    for name in original:
        raw = subprocess.check_output(["git", "show", f"{B2B}:{name}"], cwd=ROOT)
        current = (ROOT / name).read_bytes()
        rows.append(
            {
                "repository": "https://github.com/xiongQvQ/-b2b-lead-hunter-skill",
                "commit": B2B,
                "original_path": name,
                "target_path": name,
                "original_sha256": sha(raw),
                "current_sha256": sha(current),
                "license": "MIT; root LICENSE retained",
                "modification": "as-is" if raw == current else "adapted",
                "v1_execution": "wrapped"
                if Path(name).name in USED
                else "disabled"
                if name.endswith("send_smtp.py")
                else "legacy-not-used",
            }
        )
    path = "src/tradecase/vendor/ai_hunter/url_filter.py"
    rows.append(
        {
            "repository": "https://github.com/xiongQvQ/AI_Find_Customer",
            "commit": AI,
            "original_path": "backend/tools/url_filter.py",
            "target_path": path,
            "original_sha256": "5ea34d67ff15bea059c2b27b98f91db680195a35f402a55c2118ef3c5f96e3c4",
            "current_sha256": sha((ROOT / path).read_bytes()),
            "license": "MIT; adjacent LICENSE retained",
            "modification": "adapted",
            "v1_execution": "wrapped",
        }
    )
    return {"schema_version": "1.0", "sources": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = ROOT / "docs/SOURCE_MANIFEST.json"
    result = build()
    if args.check:
        if json.loads(target.read_text()) != result:
            raise SystemExit("Source manifest drift: review source mapping and regenerate explicitly")
        print("Source manifest matches 18 inherited scripts and 1 adapted AI Hunter file")
    else:
        target.write_text(json.dumps(result, indent=2) + "\n")
        print("Wrote exact source manifest")
