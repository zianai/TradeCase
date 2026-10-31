"""Explicit operator-only synthetic SDK followup; never changes normal Case runtime.

Prepare freezes one request/grant; execute refuses repeat invocation. Requires a
fresh private directory and an explicitly authorized existing key file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from datetime import timedelta
from pathlib import Path

from tradecase.p7_policy import ValidationRunPolicy, digest
from tradecase.platform import db as m
from tradecase.platform.config import Settings
from tradecase.platform.coordinator import CaseRunCoordinator, PlatformWorkflowHost
from tradecase.platform.pilot import PilotIntake, PilotService
from tradecase.platform.runtime import AgentBudget, AgentTaskRequest, OpenAIAgentRunner, SourceSnapshot
from tradecase.platform.services import CaseService
from tradecase.platform.tasks import TaskManager

REPO = Path(__file__).resolve().parents[1]
MODEL, RATE = "gpt-6.1-terra", 0.000005
RAW = (
    "SYNTHETIC E2 TEST ONLY. Buyer Clarity Retail requests 250 unprinted stainless steel drink bottles "
    "for France. Please ask for capacity, dimensions, finish, packaging, delivery date and confirmed company identity. "
    "No supplier capability, price, certification, legal compliance or email identity has been verified."
)
SOURCE = (
    "SYNTHETIC E2 SOURCE ONLY. Clarity Retail A describes reusable drinkware in France. "
    "A separate Clarity Retail B describes office furniture in Canada. These are distinct fictional entities. "
    "The inquiry does not identify which entity is the buyer. Requested quantity is 250 unprinted bottles. "
    "No official registry, corporate contact, product specification or compliance evidence is supplied."
)


def put(root, name, value):
    path = root / name
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
    path.write_text(raw + "\n")
    path.chmod(0o600)


def settings(root):
    return Settings(
        database_url="sqlite:///" + str(root / "case.sqlite"),
        checkpoint_url="sqlite:///" + str(root / "checkpoints.sqlite"),
        storage_root=root / "objects",
        work_root=root / "work",
        demo_enabled=True,
        queue_mode="inline",
        runtime="fake",
        live_model_enabled=False,
        public_fetch_enabled=False,
        outbound_enabled=False,
    )


def prepare(root):
    if root.exists():
        raise RuntimeError("Fresh directory required; never overwrite previous grants or receipts")
    root.mkdir(parents=True, mode=0o700)
    config = settings(root)
    config.prepare()
    database = m.Database(config.database_url)
    database.create_schema()
    service = CaseService(database, config)
    actor, token = service.provision("followup-synthetic-tc", "Synthetic E2 observer")
    put(root, "api-token.txt", token)
    actor = service.authenticate(token)
    now = m.utcnow()
    case = PilotService(service).intake(
        actor,
        PilotIntake(
            title="Synthetic live SDK followup — unresolved Clarity Retail",
            raw_content=RAW,
            classification="synthetic",
            synthetic=True,
            dataset_id="followup-20261031-tc-generated",
            dataset_sha256=digest(RAW.encode()),
            rights_reference="Generated synthetic fixture for authorized E2 test",
            source_locator="synthetic-inquiry.txt:line:1",
            captured_at=now - timedelta(seconds=1),
            retention_until=now + timedelta(days=7),
        ),
    )
    task = TaskManager(database).ensure(
        actor["tenant_id"],
        case["id"],
        "authorized_synthetic_sdk",
        digest({"inquiry": RAW, "source": SOURCE}),
        max_attempts=1,
    )
    request = AgentTaskRequest(
        tenant_id=actor["tenant_id"],
        case_id=case["id"],
        task_id=task.id,
        agent_run_id=m.uid(),
        goal="Analyze this explicitly fictional inquiry. Preserve both same-name candidates as unresolved. "
        "Return exact quoted observations, unknowns, conflicts, and practical follow-up questions. Never invent verified identity, "
        "email, specifications, price or compliance. This tests structured output, not business validity.",
        context={"inquiry_untrusted": RAW},
        input_refs=[case["inquiry_id"]],
        sources=[
            SourceSnapshot(
                source_id="synthetic-inquiry-source",
                url="https://synthetic.example.invalid/inquiry",
                title="Fictional inquiry input",
                text=RAW,
                captured_at=now.isoformat(),
                source_type="user_provided_unverified",
                authority="user_provided_unverified",
                license_status="permitted",
                is_synthetic=True,
            ),
            SourceSnapshot(
                source_id="synthetic-e2-source",
                url="https://synthetic.example.invalid/followup",
                title="Fictional ambiguity fixture",
                text=SOURCE,
                captured_at=now.isoformat(),
                source_type="user_provided_unverified",
                authority="user_provided_unverified",
                license_status="permitted",
                is_synthetic=True,
            ),
        ],
        allowed_tools=[],
        allowed_domains=[],
        skill_names=["buyer-research"],
        model=MODEL,
        budget=AgentBudget(
            max_turns=1,
            max_tool_calls=0,
            max_total_tokens=100000,
            max_output_tokens=5000,
            max_wall_seconds=90,
            max_cost_usd=1.0,
        ),
    )
    # Normalize optional/default numeric fields before pinning; JSON reload must
    # reproduce the same subject byte semantics used by the live runtime.
    request = AgentTaskRequest.model_validate_json(request.model_dump_json())
    context = dict(
        run_id="followup-20261031-tradecase-live",
        system="tradecase",
        tenant_id=actor["tenant_id"],
        environment="live_sandbox",
        case_id=case["id"],
        dataset_id="followup-20261031-tc-generated",
        plan_hash=digest(
            {"purpose": "one native SDK request; actual response persists; no sends or approvals", "cap": 1.0}
        ),
        input_hash=digest(request.model_dump()),
        rights_hash=digest({"rights": "generated synthetic text only"}),
        provider_config_hash=digest({"model": MODEL, "rate": RATE}),
        rights_current=True,
        data_classification="synthetic",
        action="submit_model",
        provider="openai",
        model=MODEL,
        domain="api.openai.com",
    )
    grant = {
        **{
            k: v
            for k, v in context.items()
            if k not in {"rights_current", "data_classification", "action", "provider", "model", "domain"}
        },
        "actor_id": "user-direct-followup-instruction-20261031",
        "actor_origin": "operator",
        "human_reason": "User explicitly authorized synthetic followup with existing named key and total USD10; parent allocated TradeCase USD2. This one-shot request reserves at most USD1.",
        "approved_at_utc": now.isoformat(),
        "expires_at_utc": (now + timedelta(hours=2)).isoformat(),
        "revoked_at_utc": None,
        "allow_external_writes": False,
        "export_allowed": True,
        "data_classifications": ["synthetic"],
        "capabilities": {
            "submit_model": {
                "provider": "openai",
                "model": MODEL,
                "domain": "api.openai.com",
                "max_requests": 1,
                "max_images": 0,
                "max_attempts": 1,
                "max_usd": 1.0,
            }
        },
    }
    for name, value in [
        ("request.json", request.model_dump(mode="json")),
        ("context.json", context),
        ("isolation.json", {**context, "data_root": str(root)}),
        ("grant.json", grant),
        ("dataset.json", {"inquiry": RAW, "source": SOURCE, "synthetic": True}),
        (
            "setup.json",
            {
                "case_id": case["id"],
                "actor": actor,
                "task_id": task.id,
                "allocation_usd": 2,
                "one_shot_ceiling_usd": 1,
                "pricing_source": "https://developers.openai.com/api/docs/pricing",
                "input_usd_per_million": 1,
                "output_usd_per_million": 5,
                "upper_usd_per_token": RATE,
            },
        ),
    ]:
        put(root, name, value)
    database.close()
    print(
        json.dumps({"phase": "prepared", "input_hash": context["input_hash"], "case_id": case["id"], "ceiling_usd": 1})
    )


async def execute(root, key_file):
    marker = root / "execution-started.json"
    fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump({"started_at": m.utcnow().isoformat(), "automatic_retry": False}, output)
    if (root / "reservations.sqlite").exists():
        raise RuntimeError("Existing ledger requires reconciliation, not automatic replay")
    request = AgentTaskRequest.model_validate_json((root / "request.json").read_text())
    pinned = digest((root / "grant.json").read_bytes())
    policy = ValidationRunPolicy(root, "tradecase", pinned, True)
    context = policy.context()
    if context["input_hash"] != digest(request.model_dump()):
        raise RuntimeError("Frozen request changed")
    preflight = policy.preflight(context, 1.0)
    put(root, "preflight.json", preflight)
    if preflight["status"] != "allowed":
        raise RuntimeError("Preflight blocked")
    if key_file.is_symlink() or not key_file.is_file():
        raise RuntimeError("Authorized key file unavailable")
    secret = next(
        (
            line.partition("=")[2].strip().strip("\"'")
            for line in key_file.read_text().splitlines()
            if line.strip().startswith("OPENAI_API_KEY=")
        ),
        None,
    )
    if not secret or len(secret) < 30:
        raise RuntimeError("Authorized key not present")
    os.environ.update(
        OPENAI_API_KEY=secret,
        OPENAI_AGENTS_DISABLE_TRACING="1",
        OTEL_SDK_DISABLED="true",
        ALLOW_TEST_LIVE="on",
        TRADECASE_P7_ROOT=str(root),
        TRADECASE_P7_APPROVED_GRANT_SHA256=pinned,
    )
    import httpx
    import openai

    real_client = openai.AsyncOpenAI
    receipts = []

    async def request_hook(req):
        if str(req.url) != "https://api.openai.com/v1/responses":
            raise RuntimeError("Only the exact Responses endpoint is authorized")
        put(root, "provider-request.json", json.loads(req.content))

    async def response_hook(response):
        raw = await response.aread()
        body = json.loads(raw)
        safe = raw.decode().replace(secret, "[REDACTED]")
        safe = re.sub(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}", "[REDACTED]", safe)
        if response.status_code < 300:
            put(root, "provider-response.json", json.loads(safe))
        receipt = {
            "http_status": response.status_code,
            "request_id": response.headers.get("x-request-id"),
            "response_id": body.get("id"),
            "model": body.get("model"),
            "usage": body.get("usage"),
            "error_type": body.get("error", {}).get("type") if body.get("error") else None,
            "error_code": body.get("error", {}).get("code") if body.get("error") else None,
        }
        receipts.append(receipt)
        put(root, "provider-receipts.json", receipts)

    def observed_client(**kwargs):
        kwargs["http_client"] = httpx.AsyncClient(
            trust_env=False, event_hooks={"request": [request_hook], "response": [response_hook]}
        )
        return real_client(**kwargs)

    openai.AsyncOpenAI = observed_client
    try:
        result = await OpenAIAgentRunner(
            live_enabled=True, skills_root=REPO / "skills", usd_per_token_upper_bound=RATE
        ).run(request)
    finally:
        openai.AsyncOpenAI = real_client
        os.environ.pop("OPENAI_API_KEY", None)
    put(root, "native-result.json", result.model_dump(mode="json"))
    usage = next((r["usage"] for r in receipts if r.get("usage")), None)
    summary = {
        "status": result.status,
        "stop_reason": result.stop_reason,
        "error_class": result.error_class,
        "provider": result.provider,
        "model": result.model,
        "synthetic": result.synthetic,
        "model_calls_observed": len(receipts),
        "claims": len(result.claims),
        "sources": len(result.sources),
        "unresolved_questions": result.unresolved_questions,
        "conflicts": result.conflicts,
        "token_usage": result.token_usage,
        "upper_estimated_cost_usd": result.cost_usd,
        "actual_billed_usd": None,
        "base_rate_estimate_excluding_cache_premium_usd": None
        if usage is None
        else (usage["input_tokens"] + 5 * usage["output_tokens"]) / 1000000,
        "usage_raw": usage,
        "one_shot_ceiling_usd": 1.0,
        "total_allocation_usd": 2.0,
        "external_sends": 0,
        "human_approval": False,
    }
    put(root, "summary.json", summary)
    if result.error_class or not usage:
        print(json.dumps(summary))
        return 1
    config = settings(root)
    database = m.Database(config.database_url)
    service = CaseService(database, config)
    setup = json.loads((root / "setup.json").read_text())
    manager = TaskManager(database)
    lease = manager.claim(request.tenant_id, request.task_id, "authorized-native-sdk-receipt", lease_seconds=180)
    if lease is None:
        raise RuntimeError("Cannot persist completed SDK result without exclusive task lease")
    blob = service.storage.put(result.model_dump_json().encode())
    with database.session() as session:
        session.add(
            m.AgentRun(
                id=request.agent_run_id,
                tenant_id=request.tenant_id,
                case_id=request.case_id,
                task_id=request.task_id,
                attempt_id=lease.attempt_id,
                provider=result.provider,
                model=result.model,
                runtime_id=receipts[-1].get("response_id"),
                status=result.status,
                finished_at=m.utcnow(),
                token_usage=result.token_usage,
                cost=result.cost_usd,
                stop_reason=result.stop_reason,
                artifact_refs=[blob.key],
                tool_events=[e.model_dump(mode="json") for e in result.tool_events],
                data={
                    "result_ref": blob.key,
                    "synthetic": True,
                    "cost_is_estimate": True,
                    "provenance": {**result.provenance, "provider_receipts": receipts},
                    "mode": "E2_SYNTHETIC_FOLLOWUP",
                },
            )
        )
    manager.complete(lease, {"agent_run_id": request.agent_run_id, "status": result.status})

    class RecordedLiveHost(PlatformWorkflowHost):
        async def _research(self, name, state, lease):
            # Replay one authentic, hash-pinned response into the normal graph.
            # Other research branches are explicitly unperformed/partial, never fake success.
            return {
                "research_refs": {name: request.agent_run_id} if name == "identity_research" else {},
                "research_statuses": {name: result.status if name == "identity_research" else "PARTIAL"},
            }

    coordinator = CaseRunCoordinator(service)
    coordinator.host = RecordedLiveHost(service)
    workflow = coordinator.request(setup["actor"], request.case_id)
    state = await coordinator.run(request.tenant_id, workflow["id"])
    frozen = PilotService(service).export(setup["actor"], request.case_id)
    put(root, "pilot-export.json", frozen)
    put(
        root,
        "integration.json",
        {
            "case_id": request.case_id,
            "workflow_run_id": workflow["id"],
            "state": state,
            "case_status": service.get(request.tenant_id, request.case_id)["status"],
            "approval_statuses": [a["status"] for a in service.approvals(request.tenant_id)],
            "mode": "one live SDK research result replayed into real local LangGraph; other research branches PARTIAL",
            "native_model_draft": False,
            "automatic_business_approval": False,
        },
    )
    database.close()
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare", "execute"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--key-file", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.mode == "prepare":
        prepare(root)
    else:
        raise SystemExit(asyncio.run(execute(root, args.key_file)))
