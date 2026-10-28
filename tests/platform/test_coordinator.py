"""Integrated DB + business kernel + real graph recovery tests with offline adapters."""
import asyncio
import json
from datetime import timedelta

import pytest
from sqlalchemy import update

from tradecase.platform import db as m
from tradecase.platform.config import Settings
from tradecase.platform.contracts import CreateCase, Decision, EditDraft
from tradecase.platform.coordinator import CaseRunCoordinator
from tradecase.platform.runtime import AgentTaskResult, ResearchClaim, SourceSnapshot
from tradecase.platform.services import CaseService, ServiceError


@pytest.fixture
def setup(tmp_path):
    settings = Settings(database_url="sqlite:///" + str(tmp_path / "db.sqlite"),
                        storage_root=tmp_path / "objects", work_root=tmp_path / "work",
                        checkpoint_url="sqlite:///" + str(tmp_path / "checkpoint.sqlite"), demo_enabled=True)
    settings.prepare()
    database = m.Database(settings.database_url)
    database.create_schema()
    service = CaseService(database, settings)
    _, token = service.provision("tenant-a", "reviewer")
    actor = service.authenticate(token)
    yield service, actor
    database.close()


def create(service, actor, fixture="case_strong"):
    request = CreateCase(fixture=fixture) if fixture else CreateCase(
        raw_content="Please quote widgets.", buyer_email="buyer@example.com", website="https://example.com/")
    return service.create(actor, request, "case-create")


def decision(service, actor, approval, value):
    return service.decide(actor, approval["id"], Decision(
        decision=value, artifact_hash=approval["artifact_hash"], case_version=approval["case_version"]),
        "decision-" + approval["id"])


def test_restart_duplicate_jobs_and_human_task_resolution(setup):
    service, actor = setup
    case = create(service, actor)
    coordinator = CaseRunCoordinator(service)
    run = coordinator.request(actor, case["id"])
    assert asyncio.run(coordinator.run(actor["tenant_id"], run["id"]))["status"] == "WAITING_HUMAN"
    counts = {cls: len(service.rows(actor["tenant_id"], case["id"], cls))
              for cls in (m.Source, m.Claim, m.AgentRun, m.Task)}
    restarted = CaseRunCoordinator(service)
    asyncio.run(restarted.run(actor["tenant_id"], run["id"]))
    for cls, count in counts.items():
        assert len(service.rows(actor["tenant_id"], case["id"], cls)) == count
    approval = service.approvals(actor["tenant_id"])[0]
    decision(service, actor, approval, "approve")
    assert asyncio.run(restarted.run(actor["tenant_id"], run["id"]))["status"] == "COMPLETED"
    assert all(task["status"] != "WAITING_HUMAN" for task in service.rows(actor["tenant_id"], case["id"], m.Task))
    assert len(service.followups(actor["tenant_id"])) == 1
    asyncio.run(CaseRunCoordinator(service).run(actor["tenant_id"], run["id"]))
    assert len(service.followups(actor["tenant_id"])) == 1
    runs = service.rows(actor["tenant_id"], case["id"], m.AgentRun)
    assert all(row["status"] == "COMPLETE" and row["provider"] == "fake" for row in runs)
    assert all(json.loads(service.storage.get(row["data"]["result_ref"]))["sources"] for row in runs)


def test_edit_rebinds_interrupt_and_report_uses_current_draft(setup):
    service, actor = setup
    case = create(service, actor)
    coordinator = CaseRunCoordinator(service)
    run = coordinator.request(actor, case["id"])
    asyncio.run(coordinator.run(actor["tenant_id"], run["id"]))
    original = service.approvals(actor["tenant_id"])[0]
    service.edit_draft(actor, case["id"], EditDraft(subject="Revised exact subject",
        body="Please confirm the revised sample quantity.", case_version=case["version"]))
    asyncio.run(CaseRunCoordinator(service).run(actor["tenant_id"], run["id"]))
    latest = next(a for a in service.approvals(actor["tenant_id"]) if a["status"] == "PENDING")
    assert latest["id"] != original["id"]
    decision(service, actor, latest, "approve")
    asyncio.run(CaseRunCoordinator(service).run(actor["tenant_id"], run["id"]))
    reports = [a for a in service.artifacts(actor["tenant_id"], case["id"]) if a["kind"] == "report"]
    assert "Please confirm the revised sample quantity" in reports[-1]["content"]
    assert latest["artifact_hash"] in reports[-1]["content"]
    assert all(t["status"] != "WAITING_HUMAN" for t in service.rows(actor["tenant_id"], case["id"], m.Task))


def test_revision_db_commit_before_task_receipt_is_idempotent(setup, monkeypatch):
    service, actor = setup
    case = create(service, actor)
    coordinator = CaseRunCoordinator(service)
    run = coordinator.request(actor, case["id"])
    asyncio.run(coordinator.run(actor["tenant_id"], run["id"]))
    approval = service.approvals(actor["tenant_id"])[0]
    decision(service, actor, approval, "request_changes")
    complete = coordinator.host.tasks.complete
    failed = []
    def crash_after_effect(lease, result, **kwargs):
        task = coordinator.host.tasks.get(lease.tenant_id, lease.task_id)
        if task.task_type == "draft_response" and not failed:
            failed.append(task.id)
            raise OSError("injected completion journal interruption")
        return complete(lease, result, **kwargs)
    monkeypatch.setattr(coordinator.host.tasks, "complete", crash_after_effect)
    with pytest.raises(OSError):
        asyncio.run(coordinator.run(actor["tenant_id"], run["id"]))
    assert service.get(actor["tenant_id"], case["id"])["version"] == 2
    # Simulate the scheduled retry becoming due; same Task/graph input, new attempt.
    with service.db.session() as session:
        session.execute(update(m.Task).where(m.Task.id == failed[0]).values(next_attempt_at=m.utcnow() - timedelta(seconds=1)))
    asyncio.run(CaseRunCoordinator(service).run(actor["tenant_id"], run["id"]))
    assert service.get(actor["tenant_id"], case["id"])["version"] == 2
    assert len([a for a in service.approvals(actor["tenant_id"]) if a["status"] == "PENDING"]) == 1


def test_queued_revision_cannot_change_draft_during_delivery(setup):
    """A decision committed earlier cannot bypass the fence when a worker resumes."""
    service, actor = setup
    case = create(service, actor)
    coordinator = CaseRunCoordinator(service)
    run = coordinator.request(actor, case["id"])
    asyncio.run(coordinator.run(actor["tenant_id"], run["id"]))
    approval = service.approvals(actor["tenant_id"])[0]
    decision(service, actor, approval, "request_changes")
    with service.db.session() as session:
        session.add(m.OutboundAction(
            tenant_id=actor["tenant_id"], case_id=case["id"], approval_id=approval["id"],
            artifact_hash=approval["artifact_hash"], idempotency_key="prior-worker-delivery",
            status="DISPATCHING"))
    original = service.artifacts(actor["tenant_id"], case["id"])
    with pytest.raises(ServiceError, match="finish or be reconciled"):
        coordinator.host._deterministic("draft_response", {
            "tenant_id": actor["tenant_id"], "case_id": case["id"],
            "workflow_run_id": run["id"], "input_version": case["version"], "revision_round": 1})
    assert service.get(actor["tenant_id"], case["id"])["version"] == case["version"]
    assert service.artifacts(actor["tenant_id"], case["id"]) == original


class ObservedRunner:
    def __init__(self, *, synthetic=False, delay=False):
        self.synthetic, self.delay = synthetic, delay
        self.requests = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run(self, req):
        self.requests.append(req)
        self.started.set()
        if self.delay:
            await self.release.wait()
        snapshot = SourceSnapshot(source_id="observed", url="https://example.com/about", text="Country: France",
                                  license_status="permitted", is_synthetic=self.synthetic)
        return AgentTaskResult(agent_run_id=req.agent_run_id, provider="test-contract-only",
            status="PARTIAL", synthetic=self.synthetic, sources=[snapshot],
            claims=[ResearchClaim(claim_id="country", attribute="country", text="France", classification="FACT",
                                  source_ids=["observed"], excerpt="Country: France"),
                    ResearchClaim(claim_id="unknown", attribute="registry_id", text="Not available")],
            conflicts=["Registry source and website country differ"], stop_reason="test_adapter")


def test_real_contract_sources_conflicts_unknowns_and_explicit_permissions(setup):
    service, actor = setup
    case = create(service, actor, None)
    service.settings.public_fetch_enabled = True
    service.settings.research_domains = ("example.com",)
    runner = ObservedRunner()
    coordinator = CaseRunCoordinator(service, runner)
    run = coordinator.request(actor, case["id"])
    asyncio.run(coordinator.run(actor["tenant_id"], run["id"]))
    assert runner.requests and all(set(r.allowed_tools) == {"fetch_page", "search_internal_knowledge"} for r in runner.requests)
    assert all(r.allowed_domains == ["example.com"] for r in runner.requests)
    evidence = service.evidence(actor["tenant_id"], case["id"])
    assert len(evidence["sources"]) == 1 and len(evidence["claims"]) == 2
    assert any(c["kind"] == "UNKNOWN" and not c["source_ids"] for c in evidence["claims"])
    updated = service.get(actor["tenant_id"], case["id"])
    assert "Registry source and website country differ" in updated["conflicts"]
    assert updated["research_status"] == "PARTIAL" and updated["status"] == "NEEDS_REVIEW"


def test_synthetic_sources_cannot_enter_real_case(setup):
    service, actor = setup
    case = create(service, actor, None)
    coordinator = CaseRunCoordinator(service, ObservedRunner(synthetic=True))
    run = coordinator.request(actor, case["id"])
    with pytest.raises(ServiceError, match="Synthetic source"):
        asyncio.run(coordinator.run(actor["tenant_id"], run["id"]))
    assert service.evidence(actor["tenant_id"], case["id"])["sources"] == []


def test_two_coordinators_one_workflow_lease(setup):
    service, actor = setup
    case = create(service, actor, None)
    async def scenario():
        runner = ObservedRunner(delay=True)
        first, second = CaseRunCoordinator(service, runner), CaseRunCoordinator(service)
        run = first.request(actor, case["id"])
        task = asyncio.create_task(first.run(actor["tenant_id"], run["id"]))
        await asyncio.wait_for(runner.started.wait(), 3)
        assert await second.run(actor["tenant_id"], run["id"]) == {"status": "LEASED"}
        runner.release.set()
        assert (await task)["status"] == "WAITING_HUMAN"
        assert len(runner.requests) == 3
    asyncio.run(scenario())


def test_knowledge_tool_is_tenant_scoped_versioned_and_unverified(setup):
    from pydantic import ValidationError

    from tradecase.platform.knowledge import KnowledgeInput, KnowledgeService
    from tradecase.platform.runtime import AgentTaskRequest, ExecutionBudget, ResearchResult
    service, actor = setup
    knowledge = KnowledgeService(service)
    entry = knowledge.put(actor, KnowledgeInput(title="Widget catalog", content="Our widget is certified.",
                          valid_until=m.utcnow() + timedelta(days=1)))
    registry = CaseRunCoordinator(service).host.registry
    async def scenario():
        request = AgentTaskRequest(tenant_id=actor["tenant_id"], case_id="test", task_id="test", agent_run_id="test",
                                   goal="Read widget catalog", allowed_tools=["search_internal_knowledge"])
        result = await registry.invoke("search_internal_knowledge", {"query":"widget", "url":""}, ExecutionBudget(request))
        src = result["sources"][0]
        assert src["authority"] == "user_provided_unverified"
        assert src["document_version"] == 1 and src["document_hash"] == entry["content_hash"]
        with pytest.raises(ValidationError):
            ResearchResult.model_validate({"sources":[src], "claims":[{"claim_id":"bad", "attribute":"certified",
               "text":"Certified product", "classification":"FACT", "source_ids":[src["source_id"]],
               "excerpt":"Our widget is certified."}]})
        _, token = service.provision("tenant-b", "other")
        other = request.model_copy(update={"tenant_id":"tenant-b"})
        empty = await registry.invoke("search_internal_knowledge", {"query":"widget", "url":""}, ExecutionBudget(other))
        assert empty["status"] == "NO_MATCH" and empty["sources"] == []
    asyncio.run(scenario())
