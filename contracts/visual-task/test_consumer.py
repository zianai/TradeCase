"""Stable CI gate for the real TradeCase adapter; no service or paid keys needed."""

import asyncio
import copy
import hashlib
import json

import httpx
import pytest
from verify import TOKEN, Replay, check_response, load, subset

from tradecase.visual.engine import PROTOCOL_VERSION, REMOTE_STATES, CreativeEngineClient, EngineError


def client(handler):
    return CreativeEngineClient(
        "http://127.0.0.1:4310", TOKEN, allow_local=True, transport=httpx.MockTransport(handler)
    )


@pytest.mark.parametrize("additive", [False, True])
def test_actual_adapter_against_released_provider_contract(additive):
    replay = Replay()

    def handle(request):
        body = json.loads(request.content) if request.content else None
        status, result = replay.handle(
            request.method, request.url.raw_path.decode(), dict(request.headers), body
        )
        if additive and isinstance(result, dict):
            result["future_video_capability"] = {"supported": True}
        return httpx.Response(status, content=result) if isinstance(result, bytes) else httpx.Response(status, json=result)

    async def scenario():
        engine = client(handle)
        assert PROTOCOL_VERSION == load()["version"]
        plan = await engine.plan(load()["consumer_plan"], "contract-plan")
        assert plan["requires_human_approval"] is True
        request = {"plan_id": plan["id"], "budget_usd": 0, "provider": "mock", "authorize_paid": False}
        batch = await engine.submit(request, "contract-submit")
        repeated = await engine.submit(request, "contract-submit")
        assert repeated["id"] == batch["id"]
        result = await engine.get_batch(batch["id"])
        assert result["status"] == "awaiting_asset_review" and len(result["assets"]) == 1
        asset = result["assets"][0]
        assert asset["remote_status"] == "pending"
        data, mime = await engine.get_asset(asset["id"])
        assert hashlib.sha256(data).hexdigest() == asset["sha256"] and mime == "image/png"
        assert (await engine.lookup("contract-submit", plan["id"]))["id"] == batch["id"]
        assert (await engine.cancel(batch["id"]))["status"] == "cancelled"
        replay.complete()

    asyncio.run(scenario())


@pytest.mark.parametrize("status", ["approved", "completed", "review_pending"])
def test_engine_completion_never_authorizes_business_use(status):
    assert REMOTE_STATES[status] == "awaiting_asset_review"


def test_unknown_future_state_requires_reconciliation():
    result = client(lambda _: None)._batch({
        "id": "b", "plan_id": "p", "project_id": "project", "status": "future-video-state", "cost_usd": 0
    })
    assert result["status"] == "reconciling"


@pytest.mark.parametrize("cost", [None, True, "0", -1, float("nan"), float("inf")])
def test_unknown_or_invalid_cost_is_never_reported_as_zero(cost):
    with pytest.raises(EngineError, match="invalid_remote_cost"):
        client(lambda _: None)._batch({"id": "b", "plan_id": "p", "project_id": "project", "cost_usd": cost})


def test_omitted_cost_is_not_a_free_execution_receipt():
    with pytest.raises(EngineError, match="invalid_remote_cost"):
        client(lambda _: None)._batch({"id": "b", "plan_id": "p", "project_id": "project"})


@pytest.mark.parametrize("mutation", ["truth", "reference", "provider", "batch", "mime", "qa-missing", "qa-block"])
def test_actual_adapter_enforces_asset_provenance_and_qa(mutation):
    from verify import expand
    contract = load()
    examples = {s["name"]: expand(s["fixture"], contract["fixture_bindings"]) for s in contract["steps"]}
    asset = examples["batch-asset"]
    errors = {
        "truth": "asset_truth_mismatch", "reference": "asset_reference_mismatch",
        "provider": "asset_execution_mismatch", "batch": "asset_batch_mismatch", "mime": "invalid_asset_contract",
    }
    if mutation == "truth":
        asset["truth_snapshot_id"] = "unrelated"
    elif mutation == "reference":
        asset["reference_asset_ids"] = []
    elif mutation == "provider":
        asset["provider"] = "unapproved-provider"
    elif mutation == "batch":
        asset["batch_id"] = "other-batch"
    elif mutation == "mime":
        asset["format"] = "html"
    elif mutation == "qa-missing":
        del asset["qa"]
    else:
        asset["qa"] = {"status": "pass", "checks": [], "issues": [{"severity": "block"}]}

    def handle(request):
        path = request.url.path
        result = examples["health"] if path.endswith("/health") else (
            examples["batch-review-pending"] if "/batches/" in path else (
                examples["batch-plan"] if "/plans/" in path else asset
            )
        )
        return httpx.Response(200, json=result)

    if mutation in errors:
        with pytest.raises(EngineError, match=errors[mutation]):
            asyncio.run(client(handle).get_batch("batch-fixture"))
    else:
        result = asyncio.run(client(handle).get_batch("batch-fixture"))
        assert result["assets"][0]["qa"]["status"] == ("pending" if mutation == "qa-missing" else "failed")


@pytest.mark.parametrize("code", ["engine_schema_version_mismatch", "engine_authentication_failed"])
def test_handshake_fails_before_any_write(code):
    calls = []

    def handle(request):
        calls.append(request.method)
        if code == "engine_authentication_failed":
            return httpx.Response(401, json={"error": {"code": "UNAUTHORIZED"}})
        return httpx.Response(200, json={"status": "ok", "schema_version": "2.0.0"})

    with pytest.raises(EngineError, match=code):
        asyncio.run(client(handle).submit({"plan_id": "p", "budget_usd": 0}, "key"))
    assert calls == ["GET"]


@pytest.mark.parametrize("failure", ["timeout", "server", "malformed"])
def test_ambiguous_submission_has_no_automatic_retry(failure):
    posts = []

    def handle(request):
        if request.method == "GET":
            return httpx.Response(200, json={"status": "ok", "schema_version": "1.0.0"})
        posts.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic timeout")
        return httpx.Response(503 if failure == "server" else 202, json={})

    with pytest.raises(EngineError) as error:
        asyncio.run(client(handle).submit({"plan_id": "p", "budget_usd": 0}, "one-effect"))
    assert error.value.uncertain and len(posts) == 1


def test_binary_integrity_and_fixed_origin():
    paths = []

    def handle(request):
        paths.append(str(request.url))
        if request.url.path.endswith("/health"):
            return httpx.Response(200, json={"status": "ok", "schema_version": "1.0.0"})
        if request.url.path.endswith("/file"):
            return httpx.Response(200, content=b"corrupt")
        return httpx.Response(200, json={
            "format": "png", "size_bytes": 7, "sha256": "0" * 64, "url": "http://169.254.169.254/private"
        })

    with pytest.raises(EngineError, match="asset_integrity_failure"):
        asyncio.run(client(handle).get_asset("asset"))
    assert all(path.startswith("http://127.0.0.1:4310/v1/") for path in paths)


@pytest.mark.parametrize("mutation", ["missing-field", "wrong-type", "auto-approved", "changed-budget", "changed-truth"])
def test_contract_gate_rejects_incompatible_provider_mutations(mutation):
    contract = load()
    step = next(s for s in contract["steps"] if s["name"] == "batch-asset")
    from verify import expand
    body = expand(step["fixture"], contract["fixture_bindings"])
    if mutation == "missing-field":
        del body["sha256"]
    elif mutation == "wrong-type":
        body["size_bytes"] = "123"
    elif mutation == "auto-approved":
        body["review_status"] = "approved"
    elif mutation == "changed-truth":
        body["truth_snapshot_id"] = "unrelated-truth"
    else:
        step = next(s for s in contract["steps"] if s["name"] == "submit")
        body = expand(step["fixture"], contract["fixture_bindings"])
        body["cost_usd"] = 1
    with pytest.raises((AssertionError, KeyError)):
        check_response(step, step.get("status", 200), body, contract["fixture_bindings"].copy())


def test_additive_provider_fields_are_compatible():
    expected = {"id": "asset", "review_status": "pending"}
    subset(expected, {**expected, "future_video_capability": {"supported": True}})


def test_consumer_cannot_silently_expand_data_disclosure():
    replay = Replay()
    headers = {"authorization": f"Bearer {TOKEN}", "x-api-version": PROTOCOL_VERSION, "x-request-id": "trace"}
    replay.handle("GET", "/v1/health", headers, None)
    project = copy.deepcopy(replay.steps[1])
    project["body"]["buyer_email"] = "private@example.invalid"
    with pytest.raises(AssertionError, match="request contract changed"):
        replay.handle("POST", "/v1/projects", {**headers, "idempotency-key": "contract-plan"}, project["body"])
