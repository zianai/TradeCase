"""Durable work units with atomic leases and fencing; no business orchestration."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from tradecase.platform.db import Case, Database, EventLog, Task, TaskAttempt, uid


class LeaseLost(RuntimeError):
    """A completion from an expired or superseded worker must be discarded."""


class TaskConflict(ValueError):
    pass


@dataclass(frozen=True)
class Lease:
    tenant_id: str
    case_id: str
    task_id: str
    attempt_id: str
    token: str
    worker: str
    attempt_number: int
    expires_at: datetime
    payload: dict

    @property
    def lease_token(self) -> str:
        return self.token


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _event(session, task, event_type, data):
    session.add(EventLog(
        tenant_id=task.tenant_id, case_id=task.case_id, task_id=task.id,
        event_type=event_type, data_redacted=data,
    ))


class TaskManager:
    def __init__(self, db: Database, *, clock=None):
        self.db = db
        self.clock = clock or self._database_now

    def _database_now(self):
        # Lease validity must not depend on wall-clock skew between worker hosts.
        with self.db.session() as session:
            value = session.scalar(select(func.current_timestamp()))
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    def get(self, tenant_id: str, task_id: str) -> Task:
        with self.db.session() as session:
            task = session.scalar(select(Task).where(Task.tenant_id == tenant_id, Task.id == task_id))
            if task is None:
                raise KeyError("task not found")
            return task

    def ensure(
        self, tenant_id: str, case_id: str, task_type: str, input_fingerprint: str,
        *, depends_on: list[str] | None = None, payload: dict | None = None,
        priority: int = 0, max_attempts: int = 3,
    ) -> Task:
        if not task_type or len(task_type) > 100 or not input_fingerprint or len(input_fingerprint) > 64:
            raise ValueError("task type and fingerprint are required and bounded")
        if not 1 <= max_attempts <= 10:
            raise ValueError("max_attempts must be between 1 and 10")
        deps = sorted(set(depends_on or []))
        values = payload or {}
        if len(_canonical(values).encode()) > 128 * 1024:
            raise ValueError("task payload exceeds 128 KiB; use object references")
        where = (Task.tenant_id == tenant_id, Task.case_id == case_id,
                 Task.task_type == task_type, Task.input_fingerprint == input_fingerprint)
        with self.db.session() as session:
            if session.scalar(select(Case.id).where(Case.tenant_id == tenant_id, Case.id == case_id)) is None:
                raise KeyError("case not found")
            existing = session.scalar(select(Task).where(*where))
            if existing is not None:
                return self._same(existing, deps, values)
            if deps:
                rows = session.scalars(select(Task).where(
                    Task.tenant_id == tenant_id, Task.case_id == case_id, Task.id.in_(deps),
                )).all()
                if len(rows) != len(deps):
                    raise TaskConflict("dependencies must exist in this tenant and case")
            task = Task(
                id=uid(), tenant_id=tenant_id, case_id=case_id, task_type=task_type,
                input_fingerprint=input_fingerprint, depends_on=deps, payload=values,
                priority=priority, max_attempts=max_attempts, status="PENDING" if deps else "READY",
            )
            try:
                with session.begin_nested():
                    session.add(task)
                    session.flush()
            except IntegrityError:
                existing = session.scalar(select(Task).where(*where))
                if existing is None:
                    raise
                return self._same(existing, deps, values)
            _event(session, task, "task.created", {"task_type": task_type, "status": task.status})
            return task

    @staticmethod
    def _same(task, deps, payload):
        if task.depends_on != deps or _canonical(task.payload) != _canonical(payload):
            raise TaskConflict("fingerprint reused for different input or dependencies")
        return task

    def claim(self, tenant_id: str, task_id: str, worker: str, *, lease_seconds: float = 60) -> Lease | None:
        if not worker or len(worker) > 100 or not 0 < lease_seconds <= 3600:
            raise ValueError("worker and bounded lease_seconds are required")
        now = self.clock()
        token = uid()
        expiry = now + timedelta(seconds=lease_seconds)
        with self.db.session() as session:
            task = session.scalar(select(Task).where(Task.tenant_id == tenant_id, Task.id == task_id))
            if task is None:
                raise KeyError("task not found")
            if task.depends_on:
                statuses = session.scalars(select(Task.status).where(
                    Task.tenant_id == tenant_id, Task.case_id == task.case_id, Task.id.in_(task.depends_on),
                )).all()
                if len(statuses) != len(task.depends_on) or any(s != "SUCCEEDED" for s in statuses):
                    return None
            eligible = or_(
                and_(Task.status.in_(["READY", "PENDING"]),
                     or_(Task.next_attempt_at.is_(None), Task.next_attempt_at <= now)),
                and_(Task.status == "RUNNING", Task.lease_until <= now),
            )
            claimed = session.execute(update(Task).where(
                Task.tenant_id == tenant_id, Task.id == task_id, eligible,
                Task.attempt_count < Task.max_attempts,
            ).values(
                status="RUNNING", lease_owner=worker, lease_token=token, lease_until=expiry,
                attempt_count=Task.attempt_count + 1, next_attempt_at=None, error_class=None, updated_at=now,
            ).returning(Task.id).execution_options(synchronize_session=False)).scalar_one_or_none()
            if claimed is None:
                exhausted = session.execute(update(Task).where(
                    Task.tenant_id == tenant_id, Task.id == task_id, Task.status == "RUNNING",
                    Task.lease_until <= now, Task.attempt_count >= Task.max_attempts,
                ).values(status="FAILED", error_class="LEASE_EXHAUSTED", lease_owner=None, lease_until=None)
                  .execution_options(synchronize_session=False)).rowcount
                if exhausted:
                    session.execute(update(TaskAttempt).where(
                        TaskAttempt.tenant_id == tenant_id, TaskAttempt.task_id == task_id,
                        TaskAttempt.status == "RUNNING",
                    ).values(status="LOST", finished_at=now, error_class="LEASE_EXPIRED"))
                    _event(session, task, "task.exhausted", {"error_class": "LEASE_EXHAUSTED"})
                return None
            session.refresh(task)
            session.execute(update(TaskAttempt).where(
                TaskAttempt.tenant_id == tenant_id, TaskAttempt.task_id == task_id, TaskAttempt.status == "RUNNING",
            ).values(status="LOST", finished_at=now, error_class="LEASE_EXPIRED"))
            attempt = TaskAttempt(
                id=uid(), tenant_id=tenant_id, case_id=task.case_id, task_id=task_id,
                attempt_number=task.attempt_count, lease_token=token, worker=worker, started_at=now,
            )
            session.add(attempt)
            _event(session, task, "task.claimed", {"attempt": task.attempt_count})
            return Lease(tenant_id, task.case_id, task_id, attempt.id, token, worker,
                         task.attempt_count, expiry, dict(task.payload))

    def _lease_where(self, lease: Lease, now: datetime):
        return (Task.tenant_id == lease.tenant_id, Task.id == lease.task_id,
                Task.status == "RUNNING", Task.lease_token == lease.token,
                Task.lease_owner == lease.worker, Task.lease_until > now)

    def heartbeat(self, lease: Lease, *, lease_seconds: float = 60) -> datetime:
        if not 0 < lease_seconds <= 3600:
            raise ValueError("lease_seconds must be positive and no more than 3600")
        now = self.clock()
        expiry = now + timedelta(seconds=lease_seconds)
        with self.db.session() as session:
            changed = session.execute(update(Task).where(*self._lease_where(lease, now)).values(
                lease_until=expiry, updated_at=now,
            )).rowcount
            if changed != 1:
                raise LeaseLost("task lease expired or was superseded")
        return expiry

    def complete(self, lease: Lease, result: dict, *, artifact_refs: list[str] | None = None) -> Task:
        if len(_canonical(result).encode()) > 256 * 1024:
            raise ValueError("task result exceeds 256 KiB; use object references")
        refs = artifact_refs or []
        now = self.clock()
        with self.db.session() as session:
            changed = session.execute(update(Task).where(*self._lease_where(lease, now)).values(
                status="SUCCEEDED", result=result, artifact_refs=refs, lease_owner=None,
                lease_until=None, updated_at=now,
            )).rowcount
            task = session.scalar(select(Task).where(Task.tenant_id == lease.tenant_id, Task.id == lease.task_id))
            if changed != 1:
                if (task and task.status == "SUCCEEDED" and task.lease_token == lease.token
                        and _canonical(task.result) == _canonical(result) and task.artifact_refs == refs):
                    return task
                raise LeaseLost("cannot complete a task without its current live lease")
            session.execute(update(TaskAttempt).where(
                TaskAttempt.tenant_id == lease.tenant_id, TaskAttempt.id == lease.attempt_id,
                TaskAttempt.lease_token == lease.token,
            ).values(status="SUCCEEDED", finished_at=now))
            _event(session, task, "task.succeeded", {"attempt": lease.attempt_number})
            return task

    def fail(self, lease: Lease, error_class: str, *, retryable: bool = True, base_delay: float = 1) -> Task:
        """Persist only a bounded category; never record exception bodies/credentials."""
        category = error_class if re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", error_class) else "EXECUTION_ERROR"
        if not 0 <= base_delay <= 3600:
            raise ValueError("invalid retry delay")
        now = self.clock()
        with self.db.session() as session:
            task = session.scalar(select(Task).where(Task.tenant_id == lease.tenant_id, Task.id == lease.task_id))
            retry = bool(task and retryable and task.attempt_count < task.max_attempts)
            delay = min(3600, base_delay * (2 ** max(0, lease.attempt_number - 1)))
            changed = session.execute(update(Task).where(*self._lease_where(lease, now)).values(
                status="READY" if retry else "FAILED", error_class=category,
                next_attempt_at=now + timedelta(seconds=delay) if retry else None,
                lease_owner=None, lease_until=None, updated_at=now,
            ).execution_options(synchronize_session=False)).rowcount
            if changed != 1:
                raise LeaseLost("cannot fail a task without its current live lease")
            session.refresh(task)
            session.execute(update(TaskAttempt).where(
                TaskAttempt.tenant_id == lease.tenant_id, TaskAttempt.id == lease.attempt_id,
            ).values(status="FAILED", error_class=category, finished_at=now))
            _event(session, task, "task.retry_scheduled" if retry else "task.failed",
                   {"attempt": lease.attempt_number, "error_class": category})
            return task

    def wait_human(self, lease: Lease, *, result: dict | None = None) -> Task:
        now = self.clock()
        with self.db.session() as session:
            changed = session.execute(update(Task).where(*self._lease_where(lease, now)).values(
                status="WAITING_HUMAN", result=result, lease_owner=None, lease_until=None, updated_at=now,
            )).rowcount
            if changed != 1:
                raise LeaseLost("cannot pause a task without its current live lease")
            session.execute(update(TaskAttempt).where(
                TaskAttempt.tenant_id == lease.tenant_id, TaskAttempt.id == lease.attempt_id,
            ).values(status="WAITING_HUMAN", finished_at=now))
            task = session.scalar(select(Task).where(Task.tenant_id == lease.tenant_id, Task.id == lease.task_id))
            _event(session, task, "task.waiting_human", {})
            return task

    def cancel(self, tenant_id: str, task_id: str) -> Task:
        now = self.clock()
        with self.db.session() as session:
            task = session.scalar(select(Task).where(Task.tenant_id == tenant_id, Task.id == task_id))
            if task is None:
                raise KeyError("task not found")
            if task.status == "SUCCEEDED":
                raise TaskConflict("completed work cannot be cancelled")
            if task.status == "CANCELLED":
                return task
            changed = session.execute(update(Task).where(
                Task.tenant_id == tenant_id, Task.id == task_id, Task.status != "SUCCEEDED",
            ).values(status="CANCELLED", lease_owner=None, lease_until=None, lease_token=None, updated_at=now)
              .execution_options(synchronize_session=False)).rowcount
            if not changed:
                raise TaskConflict("task completed concurrently")
            session.execute(update(TaskAttempt).where(
                TaskAttempt.tenant_id == tenant_id, TaskAttempt.task_id == task_id,
                TaskAttempt.status.in_(["RUNNING", "WAITING_HUMAN"]),
            ).values(status="CANCELLED", finished_at=now))
            session.refresh(task)
            _event(session, task, "task.cancelled", {})
            return task

    def resolve_human(self, tenant_id: str, task_id: str, result: dict | None = None) -> Task:
        """Close a paused work unit after the service validates the bound decision.

        This bookkeeping method grants no approval. Callers must first verify the
        reviewer's authority, artifact version and Case version in the service.
        """
        if result is not None and len(_canonical(result).encode()) > 256 * 1024:
            raise ValueError("task result exceeds 256 KiB; use object references")
        now = self.clock()
        with self.db.session() as session:
            task = session.scalar(select(Task).where(Task.tenant_id == tenant_id, Task.id == task_id))
            if task is None:
                raise KeyError("task not found")
            if task.status == "SUCCEEDED":
                if result is not None and _canonical(task.result) != _canonical(result):
                    raise TaskConflict("completed review task cannot change its result")
                return task
            values = {"status": "SUCCEEDED", "updated_at": now}
            if result is not None:
                values["result"] = result
            changed = session.execute(update(Task).where(
                Task.tenant_id == tenant_id, Task.id == task_id, Task.status == "WAITING_HUMAN",
                Task.lease_token == task.lease_token,
            ).values(**values).execution_options(synchronize_session=False)).rowcount
            if changed != 1:
                session.refresh(task)
                if task.status == "SUCCEEDED" and (result is None or _canonical(task.result) == _canonical(result)):
                    return task
                raise TaskConflict("task is not awaiting a human decision")
            session.execute(update(TaskAttempt).where(
                TaskAttempt.tenant_id == tenant_id, TaskAttempt.task_id == task_id,
                TaskAttempt.lease_token == task.lease_token, TaskAttempt.status == "WAITING_HUMAN",
            ).values(status="SUCCEEDED", finished_at=now))
            session.refresh(task)
            _event(session, task, "task.human_resolved", {"attempt": task.attempt_count})
            return task

    def retry(self, tenant_id: str, task_id: str) -> Task:
        """Explicit operator retry. At most ten total attempts, including manual retries."""
        with self.db.session() as session:
            task = session.scalar(select(Task).where(Task.tenant_id == tenant_id, Task.id == task_id).with_for_update())
            if task is None:
                raise KeyError("task not found")
            if task.status not in {"FAILED", "BLOCKED", "WAITING_HUMAN"}:
                raise TaskConflict("only failed, blocked or waiting work can be retried")
            if task.attempt_count >= 10:
                raise TaskConflict("hard attempt limit reached; create a new task with reviewed inputs")
            previous = task.status
            changed = session.execute(update(Task).where(
                Task.tenant_id == tenant_id, Task.id == task_id, Task.status == previous,
                Task.attempt_count == task.attempt_count,
            ).values(status="READY", max_attempts=max(task.max_attempts, task.attempt_count + 1),
                     lease_owner=None, lease_until=None, lease_token=None, next_attempt_at=None,
                     error_class=None, updated_at=self.clock())
              .execution_options(synchronize_session=False)).rowcount
            if changed != 1:
                raise TaskConflict("task changed concurrently")
            session.refresh(task)
            _event(session, task, "task.retry_requested", {"previous_status": previous})
            return task

    def ready(self, tenant_id: str, *, limit: int = 100) -> list[Task]:
        """Queue repair inventory. It proposes no new work and makes no business decisions."""
        now = self.clock()
        with self.db.session() as session:
            return list(session.scalars(select(Task).where(
                Task.tenant_id == tenant_id,
                or_(and_(Task.status.in_(["READY", "PENDING"]),
                         or_(Task.next_attempt_at.is_(None), Task.next_attempt_at <= now)),
                    and_(Task.status == "RUNNING", Task.lease_until <= now)),
            ).order_by(Task.priority.desc(), Task.created_at).limit(min(max(limit, 1), 1000))))
