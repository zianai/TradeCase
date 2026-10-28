"""Lease fencing, duplicate delivery, dependencies and crash recovery."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from sqlalchemy import select

from tradecase.platform.db import Case, Database, Inquiry, Organization, TaskAttempt, utcnow
from tradecase.platform.tasks import LeaseLost, TaskConflict, TaskManager


@pytest.fixture
def manager(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'tasks.db'}")
    db.create_schema()
    with db.session() as session:
        session.add(Organization(id="org", name="Synthetic"))
        session.flush()
        session.add(Inquiry(id="inquiry", tenant_id="org"))
        session.flush()
        session.add(Case(id="case", tenant_id="org", inquiry_id="inquiry"))
    return TaskManager(db)


def task(manager, name="research", **kwargs):
    return manager.ensure("org", "case", name, "fingerprint", **kwargs)


def test_duplicate_task_does_not_replace_original_input(manager):
    one = task(manager, payload={"source": "reference"})
    assert task(manager, payload={"source": "reference"}).id == one.id
    with pytest.raises(TaskConflict):
        task(manager, payload={"source": "changed"})


def test_two_workers_race_one_wins_and_duplicate_completion_is_safe(manager):
    item = task(manager)
    barrier = Barrier(2)

    def claim(worker):
        barrier.wait()
        return manager.claim("org", item.id, worker)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(claim, ["worker-1", "worker-2"]))
    leases = [result for result in results if result]
    assert len(leases) == 1
    assert manager.complete(leases[0], {"status": "PARTIAL"}).status == "SUCCEEDED"
    assert manager.complete(leases[0], {"status": "PARTIAL"}).status == "SUCCEEDED"
    assert manager.claim("org", item.id, "third") is None
    with pytest.raises(LeaseLost):
        manager.complete(leases[0], {"changed": True})
    with manager.db.session() as session:
        assert len(session.scalars(select(TaskAttempt)).all()) == 1


def test_expiry_new_process_recovers_and_fences_old_worker(manager):
    now = utcnow()
    manager.clock = lambda: now
    item = task(manager)
    lease = manager.claim("org", item.id, "crashed", lease_seconds=5)
    now += timedelta(seconds=6)
    restarted = TaskManager(Database(manager.db.url), clock=lambda: now)
    new = restarted.claim("org", item.id, "replacement")
    assert new.attempt_number == 2
    with pytest.raises(LeaseLost):
        manager.complete(lease, {"unsafe": True})
    with pytest.raises(LeaseLost):
        manager.heartbeat(lease)
    assert restarted.complete(new, {"recovered": True}).status == "SUCCEEDED"
    with manager.db.session() as session:
        assert [a.status for a in session.scalars(select(TaskAttempt).order_by(TaskAttempt.attempt_number))] == [
            "LOST", "SUCCEEDED",
        ]


def test_no_expired_worker_can_finish_even_without_replacement(manager):
    now = utcnow()
    manager.clock = lambda: now
    item = task(manager)
    lease = manager.claim("org", item.id, "worker", lease_seconds=1)
    now += timedelta(seconds=2)
    with pytest.raises(LeaseLost):
        manager.complete(lease, {})


def test_dependency_wait_and_tenant_scope(manager):
    first = task(manager, "identity")
    second = task(manager, "merge", depends_on=[first.id])
    assert manager.claim("org", second.id, "worker") is None
    manager.complete(manager.claim("org", first.id, "worker"), {})
    assert manager.claim("org", second.id, "worker") is not None
    with pytest.raises(KeyError):
        manager.claim("other-org", second.id, "attacker")
    with pytest.raises(TaskConflict):
        task(manager, "invalid", depends_on=["not-found"])


def test_retry_backoff_exhaustion_and_sanitized_errors(manager):
    now = utcnow()
    manager.clock = lambda: now
    item = task(manager, max_attempts=2)
    lease = manager.claim("org", item.id, "worker")
    failure = manager.fail(lease, "secret bearer abc", base_delay=10)
    assert failure.status == "READY" and failure.error_class == "EXECUTION_ERROR"
    assert manager.claim("org", item.id, "worker") is None
    now += timedelta(seconds=11)
    lease = manager.claim("org", item.id, "worker")
    assert manager.fail(lease, "TIMEOUT").status == "FAILED"
    assert manager.claim("org", item.id, "worker") is None
    assert manager.retry("org", item.id).status == "READY"
    assert manager.claim("org", item.id, "worker").attempt_number == 3


def test_crash_limit_is_terminal(manager):
    now = utcnow()
    manager.clock = lambda: now
    item = task(manager, max_attempts=1)
    manager.claim("org", item.id, "crashed", lease_seconds=1)
    now += timedelta(seconds=2)
    assert manager.claim("org", item.id, "replacement") is None
    assert manager.get("org", item.id).status == "FAILED"


def test_human_wait_releases_lease_and_cancel_invalidates_running_worker(manager):
    item = task(manager)
    lease = manager.claim("org", item.id, "worker")
    waiting = manager.wait_human(lease, result={"approval_id": "example"})
    assert waiting.status == "WAITING_HUMAN" and waiting.lease_until is None
    assert manager.claim("org", item.id, "worker") is None
    manager.retry("org", item.id)
    lease = manager.claim("org", item.id, "worker")
    manager.cancel("org", item.id)
    with pytest.raises(LeaseLost):
        manager.complete(lease, {})
    assert manager.cancel("org", item.id).status == "CANCELLED"


def test_heartbeat_extends_live_lease(manager):
    now = utcnow()
    manager.clock = lambda: now
    item = task(manager)
    lease = manager.claim("org", item.id, "worker", lease_seconds=5)
    now += timedelta(seconds=4)
    manager.heartbeat(lease, lease_seconds=10)
    now += timedelta(seconds=4)
    assert manager.complete(lease, {}).status == "SUCCEEDED"


def test_hard_manual_retry_bound(manager):
    item = task(manager, max_attempts=10)
    for _ in range(10):
        lease = manager.claim("org", item.id, "worker")
        manager.fail(lease, "TIMEOUT", base_delay=0)
    with pytest.raises(TaskConflict, match="hard attempt"):
        manager.retry("org", item.id)


def test_human_resolution_finishes_attempt_and_is_idempotent(manager):
    item = task(manager, "approval")
    lease = manager.claim("org", item.id, "worker")
    manager.wait_human(lease, result={"approval_id": "reviewed-version"})
    with pytest.raises(KeyError):
        manager.resolve_human("other-tenant", item.id)
    resolved = manager.resolve_human("org", item.id)
    assert resolved.status == "SUCCEEDED" and resolved.result == {"approval_id": "reviewed-version"}
    assert manager.resolve_human("org", item.id).status == "SUCCEEDED"
    with manager.db.session() as session:
        assert session.get(TaskAttempt, lease.attempt_id).status == "SUCCEEDED"
    with pytest.raises(TaskConflict):
        manager.resolve_human("org", item.id, {"different": "review"})


def test_human_resolution_cannot_bypass_unexecuted_work(manager):
    item = task(manager)
    with pytest.raises(TaskConflict):
        manager.resolve_human("org", item.id)
