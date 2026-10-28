import asyncio
from datetime import timedelta

from sqlalchemy import select
from test_api import api as api
from test_api import create_run

from tradecase.platform import db as m
from tradecase.platform.tasks import TaskManager
from tradecase.platform.workers import recover_due


class RecordingCoordinator:
    def __init__(self):
        self.calls = []

    async def run(self, tenant, identity):
        self.calls.append((tenant, identity))


def test_recovery_uses_current_approval_and_due_task_retry(api):
    _, app, *_ = api
    case_id = create_run(api)
    service = app.state.service
    coordinator = RecordingCoordinator()
    with service.db.session() as s:
        case = s.get(m.Case, case_id)
        run = s.get(m.WorkflowRun, case.workflow_run_id)
        run_id = run.id
        approval = s.scalar(select(m.Approval).where(m.Approval.case_id == case_id))
        approval.decision = "approved"
        approval.status = "APPROVED"
        approval_id = approval.id
        run.data = {**run.data, "current_approval_id": "unrelated-retired-id"}
    asyncio.run(recover_due({"service": service, "coordinator": coordinator}))
    assert coordinator.calls == []
    with service.db.session() as s:
        run = s.get(m.WorkflowRun, run_id)
        run.data = {**run.data, "current_approval_id": approval_id}
    asyncio.run(recover_due({"service": service, "coordinator": coordinator}))
    assert coordinator.calls == [("alpha", run_id)]
    coordinator.calls.clear()
    with service.db.session() as s:
        s.get(m.WorkflowRun, run_id).status = "FAILED"
    asyncio.run(recover_due({"service": service, "coordinator": coordinator}))
    assert coordinator.calls == []
    retry = TaskManager(service.db).ensure(
        "alpha", case_id, "retry-probe", "a" * 64, payload={"workflow_run_id": run_id}
    )
    with service.db.session() as s:
        s.get(m.Task, retry.id).next_attempt_at = m.utcnow() + timedelta(hours=1)
    asyncio.run(recover_due({"service": service, "coordinator": coordinator}))
    assert coordinator.calls == []
    with service.db.session() as s:
        s.get(m.Task, retry.id).next_attempt_at = m.utcnow() - timedelta(seconds=1)
    asyncio.run(recover_due({"service": service, "coordinator": coordinator}))
    assert coordinator.calls == [("alpha", run_id)]
