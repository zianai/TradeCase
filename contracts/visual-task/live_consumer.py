"""Optional actual consumer ↔ provider smoke test on a disposable loopback server.

CI gates remain self-contained. Run via Creative Engine's contract launcher;
never point this at the user's working database.
"""

import argparse
import asyncio
import hashlib
import re
import time

from verify import TOKEN, load

from tradecase.visual.engine import CreativeEngineClient


async def main(url):
    assert re.fullmatch(r"http://127\.0\.0\.1:\d+", url)
    engine = CreativeEngineClient(url, TOKEN, allow_local=True)
    plan = await engine.plan(load()["consumer_plan"], "live-contract-plan")
    assert plan["requires_human_approval"] is True
    payload = {"plan_id": plan["id"], "budget_usd": 0, "provider": "mock", "authorize_paid": False}
    batch = await engine.submit(payload, "live-contract-submit")
    assert (await engine.submit(payload, "live-contract-submit"))["id"] == batch["id"]
    deadline = time.monotonic() + 30
    while True:
        result = await engine.get_batch(batch["id"])
        if result["status"] not in {"queued", "running", "qa_pending"}:
            break
        assert time.monotonic() < deadline, "Batch did not finish"
        await asyncio.sleep(0.1)
    assert result["status"] == "awaiting_asset_review"
    assert result["cost_usd"] == 0 and len(result["assets"]) == 1
    asset = result["assets"][0]
    assert asset["remote_status"] == "pending"
    assert asset["truth_snapshot_id"] == plan["product"]["truth_snapshot_id"]
    data, mime = await engine.get_asset(asset["id"])
    assert hashlib.sha256(data).hexdigest() == asset["sha256"] and mime == "image/png"
    assert (await engine.lookup("live-contract-submit", plan["id"]))["id"] == batch["id"]
    assert (await engine.cancel(batch["id"]))["status"] == "cancelled"
    print("PASS actual TradeCase adapter ↔ actual Creative Engine HTTP: pending review, integrity, idempotency, reconciliation, cancellation; USD 0")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    asyncio.run(main(parser.parse_args().url))
