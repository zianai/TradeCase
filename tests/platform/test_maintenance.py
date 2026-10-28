"""Retention tests delete synthetic fixtures in temporary databases only."""

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from sqlalchemy import select

from tradecase.platform import db as m
from tradecase.platform.config import Settings
from tradecase.platform.contracts import CreateCase
from tradecase.platform.maintenance import MaintenanceService
from tradecase.platform.services import CaseService, ServiceError
from tradecase.platform.source_cache import SourceCache
from tradecase.platform.workflow import checkpoint_saver


@pytest.fixture
def setup(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'retention.db'}",
                        storage_root=tmp_path / "objects", work_root=tmp_path / "work",
                        checkpoint_url=f"sqlite:///{tmp_path / 'checkpoint.sqlite'}")
    settings.prepare()
    db = m.Database(settings.database_url)
    db.create_schema()
    service = CaseService(db, settings)
    _, token = service.provision("tenant", "Synthetic administrator")
    actor = service.authenticate(token)
    request = CreateCase(title="Synthetic retention test", raw_content="Synthetic shared original inquiry")
    case = service.create(actor, request, "case-key")
    with db.session() as session:
        row = session.get(m.Case, case["id"])
        row.status = "CLOSED"
        row.updated_at = m.utcnow() - timedelta(days=30)
    maintenance = MaintenanceService(service)
    return maintenance, actor, case["id"], request


def purge(setup, **overrides):
    maintenance, actor, case_id, _ = setup
    return asyncio.run(maintenance.purge(actor, case_id, before=m.utcnow() - timedelta(days=7),
                                         expected_version=1, idempotency_key="purge-request", **overrides))


def test_retention_defaults_to_dry_run(setup):
    maintenance, actor, case_id, _ = setup
    assert [row["case_id"] for row in maintenance.candidates(actor, m.utcnow() - timedelta(days=7))] == [case_id]
    result = purge(setup)
    assert result["dry_run"] and result["status"] == "PLANNED"
    assert maintenance.service.get(actor["tenant_id"], case_id)["status"] == "CLOSED"
    assert maintenance.verify_objects(actor) == {"checked": 1, "errors": []}


def test_purge_removes_interrupted_review_build_without_touching_other_cases(setup):
    from tradecase.platform.kernel import BusinessKernel
    maintenance, actor, case_id, _ = setup
    parent = BusinessKernel(maintenance.service).path(actor["tenant_id"], case_id, "old123").parent
    crashed = parent / ".review-build-crashed" / case_id
    crashed.mkdir(parents=True)
    (crashed / "input.json").write_text("Synthetic interrupted private input")
    other = parent / ".review-build-crashed" / "unrelated-case"
    other.mkdir()
    (other / "keep.txt").write_text("Synthetic unrelated private input")
    assert purge(setup)["derived_work_cache_count"] == 1
    assert purge(setup, dry_run=False)["status"] == "PURGED"
    assert not crashed.exists() and (other / "keep.txt").exists()


def test_purge_deletes_graph_and_preserves_minimal_replay_audit(setup):
    maintenance, actor, case_id, _ = setup
    derived = maintenance.service.settings.work_root / actor["tenant_id"] / case_id
    derived.mkdir(parents=True)
    (derived / "input.json").write_text("Synthetic private materialization")
    with maintenance.db.session() as session:
        case = session.get(m.Case, case_id)
        maintenance.service.save_artifact(session, case, "draft", {"subject": "Synthetic", "body": "Synthetic"})
    result = purge(setup, dry_run=False)
    assert result["status"] == "PURGED" and result["object_gc_required"]
    assert result["derived_work_cache_removed"] and not derived.exists()
    assert purge(setup, dry_run=False)["replayed"]
    with maintenance.db.session() as session:
        for model in (m.Case, m.Inquiry, m.Artifact, m.ArtifactVersion, m.EventLog):
            assert session.scalar(select(model)) is None
        audit = session.scalar(select(m.AuditLog))
        assert audit.action == "retention.purged" and audit.case_id is None
        assert "Synthetic shared" not in str(audit.data_redacted)
    assert maintenance.gc_orphans(minimum_age=timedelta(0))["candidates"]


def test_admin_tenant_version_and_cutoff_checks(setup):
    maintenance, actor, case_id, _ = setup
    _, token = maintenance.service.provision("other-tenant", "Other administrator")
    other = maintenance.service.authenticate(token)
    assert maintenance.candidates(other, m.utcnow()) == []
    with pytest.raises(ServiceError, match="not found"):
        asyncio.run(maintenance.purge(other, case_id, before=m.utcnow(), expected_version=1,
                                     idempotency_key="other", dry_run=False))
    with pytest.raises(ServiceError, match="changed"):
        asyncio.run(maintenance.purge(actor, case_id, before=m.utcnow(), expected_version=2,
                                     idempotency_key="version", dry_run=False))
    with pytest.raises(ServiceError, match="future"):
        maintenance.candidates(actor, m.utcnow() + timedelta(days=1))
    with maintenance.db.session() as session:
        session.get(m.User, actor["id"]).active = False
    with pytest.raises(ServiceError, match="administrator"):
        purge(setup, dry_run=False)


def test_active_workflow_blocks_even_closed_case(setup):
    maintenance, actor, case_id, _ = setup
    with maintenance.db.session() as session:
        session.add(m.WorkflowRun(tenant_id=actor["tenant_id"], case_id=case_id, status="WAITING_HUMAN"))
    with pytest.raises(ServiceError, match="Active workflow"):
        purge(setup, dry_run=False)


def test_uncertain_outbound_blocks_purge(setup):
    maintenance, actor, case_id, _ = setup
    with maintenance.db.session() as session:
        case = session.get(m.Case, case_id)
        version = maintenance.service.save_artifact(session, case, "draft", {"subject": "Synthetic"})
        approval = maintenance.service.prepare_approval(session, case, "mail_send")
        session.add(m.OutboundAction(tenant_id=actor["tenant_id"], case_id=case_id, approval_id=approval.id,
                                    artifact_hash=version.content_hash, idempotency_key="synthetic-delivery",
                                    status="DELIVERY_UNCERTAIN"))
    with pytest.raises(ServiceError, match="uncertain outbound"):
        purge(setup, dry_run=False)


def test_checkpoint_failure_preserves_business_rows_and_retry_redeletes_thread(setup):
    maintenance, actor, case_id, _ = setup
    with maintenance.db.session() as session:
        session.add(m.WorkflowRun(tenant_id=actor["tenant_id"], case_id=case_id, thread_id="closed-thread",
                                  status="COMPLETED"))
    called = []

    class Saver:
        async def adelete_thread(self, thread):
            called.append(thread)
            if len(called) == 1:
                raise RuntimeError("synthetic checkpoint unavailable after ambiguous delete")

    @asynccontextmanager
    async def factory(_url):
        yield Saver()

    maintenance.checkpoint_factory = factory
    with pytest.raises(RuntimeError, match="checkpoint unavailable"):
        purge(setup, dry_run=False)
    assert maintenance.service.get(actor["tenant_id"], case_id)["status"] == "CLOSED"
    assert purge(setup, dry_run=False)["status"] == "PURGED"
    assert called == ["closed-thread", "closed-thread"]


def test_real_sqlite_checkpoint_is_deleted_with_business_case(setup):
    maintenance, actor, case_id, _ = setup
    with maintenance.db.session() as session:
        session.add(m.WorkflowRun(tenant_id=actor["tenant_id"], case_id=case_id,
                                  thread_id="actual-synthetic-thread", status="CANCELLED"))

    async def check():
        graph = StateGraph(dict)
        graph.add_node("wait", lambda _: interrupt({"synthetic": True}))
        graph.add_edge(START, "wait")
        graph.add_edge("wait", END)
        cfg = {"configurable": {"thread_id": "actual-synthetic-thread"}}
        async with checkpoint_saver(maintenance.service.settings.checkpoint_url) as saver:
            compiled = graph.compile(checkpointer=saver)
            await compiled.ainvoke({"case_id": case_id}, cfg)
            assert await saver.aget_tuple(cfg)
        await maintenance.purge(actor, case_id, before=m.utcnow(), expected_version=1,
                                idempotency_key="actual-purge", dry_run=False)
        async with checkpoint_saver(maintenance.service.settings.checkpoint_url) as saver:
            assert await saver.aget_tuple(cfg) is None

    asyncio.run(check())


def test_gc_never_deletes_another_tenants_shared_object(setup):
    maintenance, actor, case_id, request = setup
    _, token = maintenance.service.provision("other", "Other synthetic administrator")
    other = maintenance.service.authenticate(token)
    other_case = maintenance.service.create(other, request, "other-case")
    with maintenance.db.session() as session:
        first_inquiry = session.get(m.Inquiry, session.get(m.Case, case_id).inquiry_id)
        key = first_inquiry.raw_content_ref
    purge(setup, dry_run=False)
    orphan = maintenance.storage.put(b"Synthetic unreferenced blob")
    plan = maintenance.gc_orphans(minimum_age=timedelta(0))
    assert orphan.key in plan["candidates"] and key not in plan["candidates"]
    with pytest.raises(ServiceError, match="Stop every writer"):
        maintenance.gc_orphans(dry_run=False, minimum_age=timedelta(0))
    result = maintenance.gc_orphans(dry_run=False, quiesced=True, minimum_age=timedelta(0))
    assert orphan.key in result["deleted"] and maintenance.storage.get(key)
    assert maintenance.service.get(other["tenant_id"], other_case["id"])


def test_gc_preserves_agent_and_task_json_references(setup):
    maintenance, actor, case_id, _ = setup
    ref = maintenance.storage.put(b"Synthetic task-produced evidence")
    with maintenance.db.session() as session:
        session.add(m.Task(tenant_id=actor["tenant_id"], case_id=case_id, task_type="completed",
                           input_fingerprint="synthetic", result={"nested": [{"ref": ref.key}]}))
    assert ref.key not in maintenance.gc_orphans(minimum_age=timedelta(0))["candidates"]


def test_complete_dependency_graph_deletion(setup):
    maintenance, actor, case_id, _ = setup
    scope = {"tenant_id": actor["tenant_id"], "case_id": case_id}
    with maintenance.db.session() as session:
        session.add(m.Task(id="task", **scope, task_type="identity", input_fingerprint="f", status="SUCCEEDED"))
        session.add(m.Source(id="source", **scope))
        session.add(m.Claim(id="claim", **scope, statement="Synthetic test claim"))
        session.flush()
        session.add(m.TaskAttempt(id="attempt", **scope, task_id="task", attempt_number=1,
                                  lease_token="token", worker="synthetic", status="SUCCEEDED"))
        session.add(m.ClaimEvidenceLink(**scope, claim_id="claim", source_id="source"))
        session.add(m.RiskFinding(**scope, category="synthetic"))
        session.add(m.LeadAssessment(**scope))
        session.add(m.FollowUp(**scope, next_action="Synthetic", status="COMPLETED"))
        session.flush()
        session.add(m.AgentRun(**scope, task_id="task", attempt_id="attempt", provider="fake", status="COMPLETE"))
    assert purge(setup, dry_run=False)["status"] == "PURGED"
    with maintenance.db.session() as session:
        for model in (m.Task, m.TaskAttempt, m.AgentRun, m.Source, m.Claim, m.ClaimEvidenceLink,
                      m.RiskFinding, m.LeadAssessment, m.FollowUp):
            assert session.scalar(select(model)) is None


def test_outstanding_task_blocks_purge(setup):
    maintenance, actor, case_id, _ = setup
    with maintenance.db.session() as session:
        session.add(m.Task(tenant_id=actor["tenant_id"], case_id=case_id, task_type="pending",
                           input_fingerprint="pending", status="READY"))
    with pytest.raises(ServiceError, match="Active task"):
        purge(setup, dry_run=False)


def test_verification_detects_corrupt_object_without_returning_content(setup):
    maintenance, actor, case_id, _ = setup
    with maintenance.db.session() as session:
        ref = session.get(m.Inquiry, session.get(m.Case, case_id).inquiry_id).raw_content_ref
    (maintenance.storage.root / ref).write_bytes(b"tampered private data")
    result = maintenance.verify_objects(actor)
    assert result["checked"] == 1 and result["errors"][0]["error"] == "OBJECT_INTEGRITY"
    assert "private" not in str(result)


def test_cache_and_knowledge_references_survive_gc_and_are_verified(setup):
    maintenance, actor, _case_id, _ = setup
    cache = maintenance.storage.put(b"Synthetic cached public page")
    knowledge = maintenance.storage.put(b"Synthetic internal knowledge")
    with maintenance.db.session() as session:
        session.add(SourceCache(tenant_id=actor["tenant_id"], cache_key="synthetic-cache",
                                object_ref=cache.key, expires_at=m.utcnow() - timedelta(days=1)))
        org = session.get(m.Organization, actor["tenant_id"])
        org.data = {"knowledge": [{"storage_ref": knowledge.key, "version": 1}]}
    plan = maintenance.gc_orphans(minimum_age=timedelta(0))
    assert cache.key not in plan["candidates"] and knowledge.key not in plan["candidates"]
    assert maintenance.verify_objects(actor) == {"checked": 3, "errors": []}
    maintenance.storage.delete(knowledge.key)
    errors = maintenance.verify_objects(actor)["errors"]
    assert len(errors) == 1 and errors[0]["table"] == "organizations"


def test_expired_cache_pruning_preserves_live_fetch_lease(setup):
    maintenance, actor, _case_id, _ = setup
    now = m.utcnow()
    with maintenance.db.session() as session:
        session.add(SourceCache(id="expired", tenant_id=actor["tenant_id"], cache_key="expired",
                                expires_at=now - timedelta(days=1)))
        session.add(SourceCache(id="fetching", tenant_id=actor["tenant_id"], cache_key="fetching",
                                expires_at=now - timedelta(days=1), lease_until=now + timedelta(minutes=1)))
    assert maintenance.prune_expired_cache(actor)["candidates"] == ["expired"]
    assert maintenance.prune_expired_cache(actor, dry_run=False)["deleted_rows"] == 1
    with maintenance.db.session() as session:
        assert session.get(SourceCache, "fetching") is not None


def test_purge_refuses_redirected_materialization_directory(setup, tmp_path):
    maintenance, actor, case_id, _ = setup
    outside = tmp_path / "unrelated"
    outside.mkdir()
    (outside / "keep.txt").write_text("Unrelated synthetic file")
    derived = maintenance.service.settings.work_root / actor["tenant_id"] / case_id
    derived.parent.mkdir(parents=True)
    derived.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        purge(setup, dry_run=False)
    assert (outside / "keep.txt").exists()
    assert maintenance.service.get(actor["tenant_id"], case_id)["status"] == "CLOSED"


def test_purge_removes_all_review_versions_without_touching_other_cases(setup):
    from tradecase.platform.kernel import BusinessKernel
    maintenance, actor, case_id, _ = setup
    kernel = BusinessKernel(maintenance.service)
    paths = [kernel.path(actor["tenant_id"], case_id, version) for version in (None, "older123", "latest456")]
    for path in paths:
        path.mkdir(parents=True)
        (path / "input.json").write_text("Synthetic private review inputs")
    other = kernel.path(actor["tenant_id"], "unrelated-case", "older123")
    other.mkdir(parents=True)
    (other / "input.json").write_text("Unrelated synthetic input")
    assert purge(setup)["derived_work_cache_count"] == 3
    assert purge(setup, dry_run=False)["status"] == "PURGED"
    assert all(not path.exists() for path in paths)
    assert (other / "input.json").read_text() == "Unrelated synthetic input"


def test_purge_refuses_redirected_review_version_before_any_deletion(setup, tmp_path):
    from tradecase.platform.kernel import BusinessKernel
    maintenance, actor, case_id, _ = setup
    kernel = BusinessKernel(maintenance.service)
    ordinary = kernel.path(actor["tenant_id"], case_id)
    ordinary.mkdir(parents=True)
    (ordinary / "input.json").write_text("Synthetic ordinary input")
    outside = tmp_path / "outside-review"
    outside.mkdir()
    (outside / case_id).mkdir()
    (outside / case_id / "keep.txt").write_text("Synthetic protected input")
    kernel.path(actor["tenant_id"], case_id, "version123").parent.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        purge(setup, dry_run=False)
    assert (outside / case_id / "keep.txt").exists() and (ordinary / "input.json").exists()
    assert maintenance.service.get(actor["tenant_id"], case_id)["status"] == "CLOSED"
