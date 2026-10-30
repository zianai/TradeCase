"""Versioned HTTP boundary to the independent Creative Engine.

Only transport, contract translation and result verification live here. No image
production, execution queue or visual QA is implemented by TradeCase.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx

PROTOCOL_VERSION = "1.0.0"
MAX_ASSET_BYTES = 20 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
REMOTE_STATES = {
    "draft": "queued",
    "planned": "queued",
    "queued": "queued",
    "running": "running",
    "qa_pending": "qa_pending",
    "review_pending": "awaiting_asset_review",
    "completed": "awaiting_asset_review",
    "approved": "awaiting_asset_review",
    "rejected": "awaiting_asset_review",
    "revision_pending": "awaiting_asset_review",
    "failed": "failed",
    "blocked": "blocked",
    "cancelled": "cancelled",
    "paused": "blocked",
    "reconciling": "reconciling",
    "needs_input": "blocked",
}
# A static transport fixture, deliberately not an image generator.
MOCK_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC"
)


class EngineError(RuntimeError):
    def __init__(self, code: str, *, uncertain: bool = False):
        self.code, self.uncertain = code, uncertain
        super().__init__(code)


def _id(value):
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise EngineError("invalid_remote_identifier")
    return value


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise EngineError("invalid_remote_cost")
    return value


def _source(source):
    required = {
        "external_id",
        "filename",
        "data_base64",
        "kind",
        "authorized",
        "verified",
        "sensitive_data_cleared",
        "source_version",
    }
    if (
        not required.issubset(source)
        or source["authorized"] is not True
        or source["sensitive_data_cleared"] is not True
    ):
        raise EngineError("source_authorization_required")
    _id(source["external_id"])
    name = source["filename"]
    if (
        not isinstance(name, str)
        or not 1 <= len(name) <= 240
        or re.search(r"[\\/\x00-\x1f]", name)
        or name in {".", ".."}
    ):
        raise EngineError("invalid_source_filename")
    if source["kind"] not in {"product_photo", "cutout", "logo", "reference", "document"}:
        raise EngineError("invalid_source_kind")
    try:
        data = base64.b64decode(source["data_base64"], validate=True)
    except (ValueError, TypeError):
        raise EngineError("invalid_source_bytes") from None
    if not 0 < len(data) <= MAX_ASSET_BYTES:
        raise EngineError("source_size_limit")
    return {k: source[k] for k in required if k != "external_id"}


class CreativeEngineClient:
    """Uses fixed service endpoints; never fetches a URL supplied by an asset.

    A service token is required even for loopback deployments. Loopback HTTP is
    an explicit development opt-in. Auth enforcement on the server must also be
    enabled by its operator. Transport injection is for contract tests only.
    """

    mode = "http"

    def __init__(self, base_url: str, token: str, *, allow_local: bool = False, transport=None):
        u = urlsplit(base_url)
        local = u.hostname in {"127.0.0.1", "::1", "localhost"}
        if u.username or u.password or u.query or u.fragment or u.path not in {"", "/", "/v1", "/v1/"}:
            raise EngineError("invalid_engine_url")
        if not u.hostname or (u.scheme != "https" and not (allow_local and local and u.scheme == "http")):
            raise EngineError("engine_tls_required")
        if not token or any(ch in token for ch in "\r\n"):
            raise EngineError("engine_token_required")
        self.base_url = base_url.rstrip("/").removesuffix("/v1") + "/v1"
        self.token, self.transport = token, transport
        self.engine_identity = {"mode": self.mode, "endpoint": self.base_url, "protocol": PROTOCOL_VERSION}
        self._verified = False

    async def _request(self, method, path, *, payload=None, key=None, binary=False, missing=False):
        headers = {
            "Authorization": "Bearer " + self.token,
            "X-API-Version": PROTOCOL_VERSION,
            "X-Request-ID": hashlib.sha256((key or path).encode()).hexdigest()[:32],
        }
        if key:
            if not 1 <= len(key) <= 200 or re.search(r"[\x00-\x1f\x7f]", key):
                raise EngineError("invalid_idempotency_key")
            headers["Idempotency-Key"] = key
        limit = MAX_ASSET_BYTES if binary else MAX_JSON_BYTES
        try:
            async with httpx.AsyncClient(
                timeout=30, follow_redirects=False, trust_env=False, transport=self.transport
            ) as client:
                async with client.stream(method, self.base_url + path, json=payload, headers=headers) as response:
                    if response.status_code == 404 and missing:
                        return None
                    if response.status_code >= 400 or 300 <= response.status_code < 400:
                        code = {
                            401: "engine_authentication_failed",
                            403: "engine_forbidden",
                            409: "engine_conflict",
                            429: "engine_rate_limited",
                        }.get(response.status_code, "engine_http_error")
                        raise EngineError(code, uncertain=method == "POST" and response.status_code >= 500)
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > limit:
                            raise EngineError("engine_response_size_limit", uncertain=method == "POST")
                    if binary:
                        return bytes(content)
                    try:
                        value = json.loads(content)
                    except (ValueError, UnicodeDecodeError):
                        raise EngineError("invalid_engine_json", uncertain=method == "POST") from None
                    if not isinstance(value, dict):
                        raise EngineError("invalid_engine_contract", uncertain=method == "POST")
                    return value
        except httpx.HTTPError:
            # A timed-out POST may have durably queued a paid operation.
            raise EngineError("engine_transport_error", uncertain=method == "POST") from None

    async def health(self):
        value = await self._request("GET", "/health")
        if value.get("schema_version") != PROTOCOL_VERSION or value.get("status") != "ok":
            raise EngineError("engine_schema_version_mismatch")
        self._verified = True
        return value

    async def _check(self):
        if not self._verified:
            await self.health()

    async def plan(self, payload: dict, key: str):
        await self._check()
        sources = payload.get("source_assets", [])
        if len(sources) > 32:
            raise EngineError("source_count_limit")
        validated = [_source(s) for s in sources]
        if len({s["external_id"] for s in sources}) != len(sources):
            raise EngineError("duplicate_source_identifier")
        project = await self._request(
            "POST",
            "/projects",
            payload={"name": "TradeCase visual " + _id(payload["visual_task_id"]), "product_id": payload["product_id"]},
            key=key,
        )
        project_id = _id(project.get("id"))
        mapping = {}
        for original, source in zip(sources, validated):
            remote = await self._request("POST", "/assets/import", payload={**source, "project_id": project_id})
            mapping[original["external_id"]] = _id(remote.get("id"))
        truth = payload.get("truth_snapshot")
        truth_id = None
        if truth:
            facts = []
            for fact in truth.get("facts", []):
                source_id = mapping.get(fact.get("source_asset_id"))
                if source_id is None:
                    raise EngineError("truth_source_not_provided")
                # Explicit field selection avoids transferring unrelated buyer data.
                facts.append(
                    {
                        k: fact[k]
                        for k in (
                            "name",
                            "value",
                            "source_version",
                            "evidence_status",
                            "confirmed_at",
                            "external_allowed",
                        )
                    }
                    | {"source_asset_id": source_id}
                )
            result = await self._request(
                "POST",
                "/truth-snapshots",
                payload={
                    "project_id": project_id,
                    "product_id": payload["product_id"],
                    "version": str(truth["version"]),
                    "facts": facts,
                },
            )
            truth_id = _id(result.get("id"))
        brief = {
            "project_id": project_id,
            "source": {"system": "tradecase", "external_id": payload["visual_task_id"]},
            "workflow": "buyer-proposal",
            "intent": payload["intent"],
            "requirements": payload["requirements"],
            "product": {
                "product_id": payload["product_id"],
                "stage": "concept" if payload.get("concept") else "existing_sku",
            },
            "reference_asset_ids": [mapping[s["external_id"]] for s in sources if s["kind"] != "document"],
            "fidelity": "exploratory" if payload.get("concept") else payload.get("fidelity", "controlled"),
            "allowed_changes": payload.get("allowed_changes", []),
            "forbidden_changes": payload.get("forbidden_changes", []),
            "variants": payload["variants"],
            "budget_usd": payload["budget_usd"],
            "provider": payload.get("provider", "mock"),
            "delivery_target": "buyer_review",
            "scenes": ["Studio"],
        }
        if truth_id:
            brief["product"]["truth_snapshot_id"] = truth_id
        logos = [mapping[s["external_id"]] for s in sources if s["kind"] == "logo"]
        if logos:
            brief["authorized_logo_asset_id"] = logos[0]
        saved = await self._request("POST", "/briefs", payload=brief)
        result = await self._request("POST", "/briefs/" + _id(saved.get("id")) + "/plan")
        _id(result.get("id"))
        if result.get("requires_human_approval") is not True or result.get("strategy") not in {
            "reuse",
            "compose",
            "edit",
            "generate",
            "blocked",
        }:
            raise EngineError("invalid_engine_plan")
        if (
            result.get("variants") != brief["variants"]
            or result.get("allowed_changes") != brief["allowed_changes"]
            or result.get("forbidden_changes") != brief["forbidden_changes"]
        ):
            raise EngineError("engine_plan_scope_changed")
        return result

    async def submit(self, payload: dict, key: str):
        await self._check()
        body = {
            "plan_id": _id(payload["plan_id"]),
            "budget_usd": _finite(payload["budget_usd"]),
            "authorize_paid": payload.get("authorize_paid") is True,
            "vision_review": False,
            "provider": payload.get("provider", "mock"),
        }
        result = await self._request("POST", "/batches", payload=body, key=key)
        try:
            return self._batch(result)
        except EngineError as exc:
            raise EngineError(exc.code, uncertain=True) from None

    def _batch(self, value):
        return {
            "id": _id(value.get("id")),
            "plan_id": _id(value.get("plan_id")),
            "project_id": _id(value.get("project_id")),
            "status": REMOTE_STATES.get(value.get("status"), "reconciling"),
            "remote_status": value.get("status"),
            "cost_usd": _finite(value.get("cost_usd", 0)),
            "provider": value.get("provider"),
            "assets": [],
            "tasks": value.get("tasks", []),
        }

    async def get_batch(self, batch_id: str):
        await self._check()
        value = await self._request("GET", "/batches/" + _id(batch_id))
        result = self._batch(value)
        if not isinstance(result["tasks"], list) or len(result["tasks"]) > 256:
            raise EngineError("invalid_batch_tasks")
        remote_plan = None
        if any(task.get("asset_id") for task in result["tasks"]):
            remote_plan = await self._request("GET", "/plans/" + result["plan_id"])
            if remote_plan.get("id") != result["plan_id"] or remote_plan.get("project_id") != result["project_id"]:
                raise EngineError("batch_plan_mismatch")
        for task in result["tasks"]:
            if task.get("plan_id") != result["plan_id"] or task.get("batch_id") != batch_id:
                raise EngineError("task_batch_mismatch")
            if task.get("asset_id"):
                asset = await self._request("GET", "/assets/" + _id(task["asset_id"]))
                if asset.get("batch_id") != batch_id or asset.get("project_id") != result["project_id"]:
                    raise EngineError("asset_batch_mismatch")
                # 1.0.0 delegates reuse/compose to its deterministic compositor;
                # batch.provider still names the configured fallback image provider.
                expected_providers = {result["provider"]}
                if remote_plan.get("strategy") in {"reuse", "compose"}:
                    expected_providers.add("deterministic")
                if (
                    asset.get("task_id") != task.get("id")
                    or asset.get("provider") not in expected_providers
                    or task.get("provider") != result["provider"]
                ):
                    raise EngineError("asset_execution_mismatch")
                if asset.get("truth_snapshot_id") != remote_plan.get("product", {}).get("truth_snapshot_id"):
                    raise EngineError("asset_truth_mismatch")
                if set(asset.get("reference_asset_ids", [])) != set(remote_plan.get("reference_asset_ids", [])):
                    raise EngineError("asset_reference_mismatch")
                qa = asset.get("qa") or {}
                qa_status = qa.get("status")
                if (
                    not isinstance(asset.get("sha256"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", asset["sha256"])
                    or asset.get("format") not in {"png", "jpeg", "webp"}
                    or asset.get("identity") not in {"real_product", "concept", "mock"}
                    or not isinstance(asset.get("size_bytes"), int)
                    or not 0 < asset["size_bytes"] <= MAX_ASSET_BYTES
                ):
                    raise EngineError("invalid_asset_contract")
                if any(issue.get("severity") == "block" for issue in qa.get("issues", [])) or any(
                    check.get("status") == "block" for check in qa.get("checks", [])
                ):
                    qa_status = "block"
                # Engine does all visual QA; missing QA can never mean pass.
                result["assets"].append(
                    {
                        "id": _id(asset.get("id")),
                        "sha256": asset.get("sha256"),
                        "mime_type": "image/" + str(asset.get("format")),
                        "identity": asset.get("identity"),
                        "qa": {
                            "status": "failed"
                            if qa_status == "block"
                            else "passed"
                            if qa_status in {"pass", "warn"}
                            else "pending",
                            "issues": qa.get("issues", []),
                            "report": qa,
                        },
                        "plan_id": result["plan_id"],
                        "truth_snapshot_id": asset.get("truth_snapshot_id"),
                        "remote_status": asset.get("review_status"),
                        "size_bytes": asset.get("size_bytes"),
                        "provider": asset.get("provider"),
                        "allowed_uses": asset.get("allowed_uses", []),
                    }
                )
        return result

    async def lookup(self, key: str, plan_id: str | None = None):
        # 1.0.0 has no GET-by-idempotency-key. A persisted unique plan is the
        # reconciliation handle. An absent result is NOT permission to retry.
        await self._check()
        if not plan_id:
            raise EngineError("reconciliation_requires_plan_id", uncertain=True)
        matches = []
        for offset in range(0, 10000, 200):
            page = await self._request("GET", f"/batches?limit=200&offset={offset}")
            items = page.get("items")
            if not isinstance(items, list):
                raise EngineError("invalid_engine_contract", uncertain=True)
            matches.extend(b for b in items if b.get("plan_id") == plan_id)
            if offset + len(items) >= page.get("total", 0):
                break
        else:
            raise EngineError("reconciliation_scan_limit", uncertain=True)
        if len(matches) > 1:
            raise EngineError("ambiguous_remote_batches", uncertain=True)
        return await self.get_batch(matches[0]["id"]) if matches else None

    async def get_asset(self, asset_id: str):
        await self._check()
        metadata = await self._request("GET", "/assets/" + _id(asset_id))
        mime = "image/" + str(metadata.get("format"))
        if mime not in {"image/png", "image/jpeg", "image/webp"}:
            raise EngineError("unsupported_asset_format")
        data = await self._request("GET", "/assets/" + _id(asset_id) + "/file", binary=True)
        if (
            not data
            or hashlib.sha256(data).hexdigest() != metadata.get("sha256")
            or len(data) != metadata.get("size_bytes")
        ):
            raise EngineError("asset_integrity_failure")
        valid = (
            (mime == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n"))
            or (mime == "image/jpeg" and data.startswith(b"\xff\xd8\xff"))
            or (mime == "image/webp" and data.startswith(b"RIFF") and data[8:12] == b"WEBP")
        )
        if not valid:
            raise EngineError("asset_signature_mismatch")
        return data, mime

    async def cancel(self, batch_id: str):
        await self._check()
        return self._batch(await self._request("POST", "/batches/" + _id(batch_id) + "/cancel"))


class DisabledCreativeEngine:
    mode = "disabled"
    engine_identity = {"mode": "disabled", "protocol": PROTOCOL_VERSION}

    async def health(self, *args, **kwargs):
        raise EngineError("creative_engine_unavailable")

    plan = submit = get_batch = lookup = get_asset = cancel = health


class MockCreativeEngine:
    """Offline contract fixture. No API/provider calls, no production images."""

    mode = "mock"
    engine_identity = {"mode": "mock", "protocol": PROTOCOL_VERSION, "fixture": "static-png-v2"}

    def __init__(self, state_path=None):
        self.plans, self.batches, self.keys, self.assets = {}, {}, {}, {}
        self.state_path = Path(state_path) if state_path else None

    @contextmanager
    def _state(self):
        if self.state_path is None:
            yield
            return
        # A persisted fake remote service fixture, never a production worker.
        import fcntl

        path = self.state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = path.with_suffix(path.suffix + ".lock")
        if path.is_symlink() or lock.is_symlink():
            raise EngineError("unsafe_mock_state_path")
        with lock.open("a+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            if path.exists():
                if path.stat().st_size > 10 * 1024 * 1024:
                    raise EngineError("mock_state_size_limit")
                data = json.loads(path.read_text())
                self.plans, self.batches, self.keys, self.assets = (
                    data[k] for k in ("plans", "batches", "keys", "assets")
                )
            yield
            data = json.dumps({"plans": self.plans, "batches": self.batches, "keys": self.keys, "assets": self.assets})
            with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, prefix=".mock-") as temp:
                temp.write(data)
                temp.flush()
                os.fsync(temp.fileno())
                temp_name = temp.name
            os.replace(temp_name, path)
            fcntl.flock(handle, fcntl.LOCK_UN)

    async def health(self):
        return {"status": "ok", "schema_version": PROTOCOL_VERSION, "provider": "mock"}

    async def plan(self, payload, key):
        with self._state():
            rid = "mock_plan_" + hashlib.sha256(key.encode()).hexdigest()[:24]
            self.plans[rid] = {
                "id": rid,
                "project_id": "mock_project",
                "strategy": "generate" if payload.get("concept") else "compose",
                "fidelity": "exploratory" if payload.get("concept") else payload.get("fidelity", "controlled"),
                "variants": payload["variants"],
                "budget_usd": payload["budget_usd"],
                "estimated_cost_usd": 0,
                "blocked_reasons": [],
                "requires_human_approval": True,
                "mock": True,
                "allowed_changes": payload.get("allowed_changes", []),
                "forbidden_changes": payload.get("forbidden_changes", []),
            }
            return self.plans[rid]

    async def submit(self, payload, key):
        with self._state():
            fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            if key in self.keys:
                old, rid = self.keys[key]
                if old != fingerprint:
                    raise EngineError("engine_conflict")
                return self.batches[rid]
            plan = self.plans.get(payload["plan_id"])
            if plan is None:
                raise EngineError("engine_plan_not_found")
            rid = "mock_batch_" + hashlib.sha256(key.encode()).hexdigest()[:24]
            assets = []
            for number in range(plan["variants"]):
                aid = rid + "_" + str(number)
                self.assets[aid] = True
                assets.append(
                    {
                        "id": aid,
                        "sha256": hashlib.sha256(MOCK_PNG).hexdigest(),
                        "mime_type": "image/png",
                        "identity": "mock",
                        "qa": {"status": "passed", "issues": [], "report": {"mode": "mock_fixture_not_visual_qa"}},
                        "plan_id": payload["plan_id"],
                        "allowed_uses": ["buyer_review"],
                        "size_bytes": len(MOCK_PNG),
                    }
                )
            self.batches[rid] = {
                "id": rid,
                "plan_id": payload["plan_id"],
                "project_id": "mock_project",
                "status": "awaiting_asset_review",
                "remote_status": "review_pending",
                "cost_usd": 0,
                "provider": "mock",
                "assets": assets,
                "tasks": [],
            }
            self.keys[key] = fingerprint, rid
            return self.batches[rid]

    async def get_batch(self, batch_id):
        with self._state():
            if batch_id not in self.batches:
                raise EngineError("engine_batch_not_found")
            return self.batches[batch_id]

    async def lookup(self, key, plan_id=None):
        with self._state():
            return self.batches[self.keys[key][1]] if key in self.keys else None

    async def get_asset(self, asset_id):
        with self._state():
            if asset_id not in self.assets:
                raise EngineError("engine_asset_not_found")
            return MOCK_PNG, "image/png"

    async def cancel(self, batch_id):
        with self._state():
            self.batches[batch_id] = {**self.batches[batch_id], "status": "cancelled"}
            return self.batches[batch_id]


def engine_from_env():
    mode = os.getenv("TRADECASE_CREATIVE_ENGINE_MODE", "disabled")
    if mode == "disabled":
        return DisabledCreativeEngine()
    if mode == "mock":
        return MockCreativeEngine(os.getenv("TRADECASE_CREATIVE_MOCK_STATE", ".tradecase/creative-mock-fixture.json"))
    if mode != "http":
        raise EngineError("unsupported_engine_mode")
    return CreativeEngineClient(
        os.getenv("TRADECASE_CREATIVE_ENGINE_URL", ""),
        os.getenv("TRADECASE_CREATIVE_ENGINE_TOKEN", ""),
        allow_local=os.getenv("TRADECASE_CREATIVE_ENGINE_ALLOW_LOCAL") == "true",
    )
