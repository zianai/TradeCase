"""At-least-once wakeups. DB leases and graph own all durable work."""

from __future__ import annotations

import asyncio

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import or_, select

from tradecase.platform import db as m
from tradecase.platform.config import Settings
from tradecase.platform.coordinator import CaseRunCoordinator
from tradecase.platform.services import CaseService


async def startup(ctx):
    settings = Settings()
    settings.prepare()
    ctx["service"] = CaseService(m.Database(settings.database_url), settings)
    ctx["coordinator"] = CaseRunCoordinator(ctx["service"])


async def shutdown(ctx):
    ctx["service"].db.close()


async def run_case_job(ctx, tenant_id, workflow_run_id):
    return await ctx["coordinator"].run(tenant_id, workflow_run_id)


async def recover_due(ctx):
    service = ctx["service"]
    now = m.utcnow()
    with service.db.session() as s:
        # Failed work needs controlled Task retry; waiting humans only wake after persisted decisions.
        runs = s.scalars(
            select(m.WorkflowRun).where(
                m.WorkflowRun.status.in_(["PENDING", "RUNNING", "WAITING_HUMAN", "FAILED"]),
                or_(m.WorkflowRun.lease_until.is_(None), m.WorkflowRun.lease_until <= now),
            )
        ).all()
        work = []
        for run in runs:
            if run.status == "FAILED":
                retry = s.scalar(select(m.Task.id).where(
                    m.Task.tenant_id == run.tenant_id, m.Task.case_id == run.case_id,
                    m.Task.payload["workflow_run_id"].as_string() == run.id,
                    m.Task.status == "READY", m.Task.attempt_count < m.Task.max_attempts,
                    or_(m.Task.next_attempt_at.is_(None), m.Task.next_attempt_at <= now)))
                if not retry:
                    continue
            if run.status == "WAITING_HUMAN":
                approval_id = run.data.get("current_approval_id")
                if not approval_id:
                    continue
                approval = s.scalar(
                    select(m.Approval).where(
                        m.Approval.tenant_id == run.tenant_id,
                        m.Approval.id == approval_id,
                        m.Approval.case_id == run.case_id,
                        m.Approval.decision.is_not(None),
                        m.Approval.status != "INVALIDATED",
                    )
                )
                if not approval:
                    continue
            work.append((run.tenant_id, run.id))
        for f in s.scalars(select(m.FollowUp).where(m.FollowUp.status == "PENDING", m.FollowUp.due_at <= now)):
            key = "followup-due:" + f.id + ":" + str(f.version)
            exists = s.scalar(
                select(m.EventLog.id).where(m.EventLog.tenant_id == f.tenant_id, m.EventLog.idempotency_key == key)
            )
            if not exists:
                s.add(
                    m.EventLog(
                        tenant_id=f.tenant_id,
                        case_id=f.case_id,
                        event_type="followup.due",
                        idempotency_key=key,
                        data_redacted={"status": "DUE"},
                    )
                )
    for tenant, run_id in work:
        if "redis" in ctx:
            await ctx["redis"].enqueue_job("run_case_job", tenant, run_id)
        else:
            try:
                await ctx["coordinator"].run(tenant, run_id)
            except Exception:
                pass


async def recover_local(service, coordinator):
    while True:
        try:
            await recover_due({"service": service, "coordinator": coordinator})
        except Exception:
            pass
        await asyncio.sleep(5)


class WorkerSettings:
    functions = [run_case_job]
    on_startup = startup
    on_shutdown = shutdown
    cron_jobs = [cron(recover_due, second={0, 15, 30, 45}, run_at_startup=True)]
    redis_settings = RedisSettings.from_dsn(Settings().redis_url)
    max_jobs = 8
    job_timeout = 180
    max_tries = 1  # TaskManager owns attempts; no multiplied queue retry policy.
