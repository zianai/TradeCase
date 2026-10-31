"""Actual TradeCase CE consumer, only a disposable loopback Mock provider.

Consumes the immutable 1.0.0 fixture, with isolated identifiers. No model keys.
"""
import argparse
import asyncio
import hashlib
import json
import re
import time
from pathlib import Path
from uuid import uuid4

from tradecase.visual.engine import CreativeEngineClient

ROOT = Path(__file__).resolve().parents[1]


async def smoke(url, token_file):
    if not re.fullmatch(r"http://127\.0\.0\.1:\d+", url):
        raise ValueError("Only an explicitly isolated loopback provider is permitted")
    if token_file.is_symlink() or not token_file.is_file() or token_file.stat().st_mode & 0o077:
        raise ValueError("A private synthetic service token file is required")
    engine = CreativeEngineClient(url, token_file.read_text().strip(), allow_local=True)
    fixture = json.loads((ROOT / "contracts/visual-task/1.0.0/contract.json").read_text())["consumer_plan"]
    identity = "tc-p8-" + uuid4().hex
    fixture.update(visual_task_id=identity, product_id=identity)
    plan = await engine.plan(fixture, identity + "-plan")
    assert plan["requires_human_approval"] is True
    payload = {"plan_id": plan["id"], "budget_usd": 0, "provider": "mock", "authorize_paid": False}
    batch = await engine.submit(payload, identity + "-submit")
    assert (await engine.submit(payload, identity + "-submit"))["id"] == batch["id"]
    deadline = time.monotonic() + 45
    while True:
        result = await engine.get_batch(batch["id"])
        if result["status"] not in {"queued", "running", "qa_pending"}:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError("Local worker did not finish")
        await asyncio.sleep(0.1)
    assert result["status"] == "awaiting_asset_review"
    assert result["cost_usd"] == 0 and len(result["assets"]) == 1
    asset = result["assets"][0]
    assert asset["remote_status"] == "pending"
    assert asset["truth_snapshot_id"] == plan["product"]["truth_snapshot_id"]
    data, mime = await engine.get_asset(asset["id"])
    assert hashlib.sha256(data).hexdigest() == asset["sha256"] and mime == "image/png"
    assert (await engine.lookup(identity + "-submit", plan["id"]))["id"] == batch["id"]
    assert (await engine.cancel(batch["id"]))["status"] == "cancelled"
    print(json.dumps({"status": "passed", "mode": "E1 synthetic Mock HTTP", "consumer": "tradecase",
                      "product_id": identity, "plan_id": plan["id"], "batch_id": batch["id"],
                      "asset_sha256": asset["sha256"], "human_review": "pending", "paid_calls": 0}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(smoke(args.url, args.token_file))
