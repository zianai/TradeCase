"""Case resources with token RBAC, tenant filtering and replayable SSE."""

from __future__ import annotations

import asyncio
import io
import json
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Header, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy.exc import IntegrityError

from tradecase.platform import db as m
from tradecase.platform.actions import OutboxService
from tradecase.platform.config import Settings
from tradecase.platform.contracts import (
    CancelAction,
    CaseMetadata,
    CloseCase,
    CreateCase,
    Decision,
    EditDraft,
    FollowUpInput,
    Postpone,
    Reconciliation,
    SendApproval,
    SendRequest,
)
from tradecase.platform.coordinator import CaseRunCoordinator
from tradecase.platform.knowledge import KnowledgeInput, KnowledgeService
from tradecase.platform.review_inputs import ReviewInputs, ReviewInputsService
from tradecase.platform.services import CaseService, ServiceError
from tradecase.platform.source_intake import SourceInput, SourceIntakeService
from tradecase.platform.tasks import TaskConflict, TaskManager


def create_app(settings=None, db=None, runner=None, connector=None):
    settings = settings or Settings()
    settings.prepare()
    db = db or m.Database(settings.database_url)
    service = CaseService(db, settings)
    coordinator = CaseRunCoordinator(service, runner)
    outbox = OutboxService(service, connector)
    pending = set()

    @asynccontextmanager
    async def lifespan(app):
        # local queue also recovers DB work after process restart; production ARQ runs a separate worker.
        if settings.queue_mode == "local":
            from tradecase.platform.workers import recover_local

            task = asyncio.create_task(recover_local(service, coordinator))
            pending.add(task)
        yield
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    app = FastAPI(title="TradeCase Case Workbench", version="1.0.0", lifespan=lifespan)
    app.state.service = service
    app.state.coordinator = coordinator
    app.state.outbox = outbox

    @app.exception_handler(ServiceError)
    async def domain_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.exception_handler(ValueError)
    async def invalid_input(request, exc):
        return JSONResponse({"detail": "Invalid input or integrity check failed"}, status_code=422)

    @app.exception_handler(TaskConflict)
    async def task_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(IntegrityError)
    async def integrity_error(request, exc):
        return JSONResponse({"detail": "Conflicting transaction; reload and retry with the same key"}, status_code=409)

    @app.middleware("http")
    async def security(request, call_next):
        size = request.headers.get("content-length", "0")
        if not size.isdigit() or int(size) > settings.max_upload_bytes + 16384:
            return JSONResponse({"detail": "Request exceeds size limit"}, status_code=413)
        if request.method in {"POST", "PATCH", "PUT"}:
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > settings.max_upload_bytes + 16384:
                    return JSONResponse({"detail": "Request exceeds size limit"}, status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def actor(authorization: str = Header(default="")):
        if not authorization.startswith("Bearer "):
            raise ServiceError("Bearer credential required", 401)
        return service.authenticate(authorization[7:])

    def idem(idempotency_key: str = Header(alias="Idempotency-Key")):
        if not 1 <= len(idempotency_key) <= 160:
            raise ServiceError("Idempotency-Key must contain 1–160 characters", 422)
        return idempotency_key

    async def wake(tenant, run_id):
        if settings.queue_mode == "arq":
            from arq import create_pool
            from arq.connections import RedisSettings

            try:
                redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
                await redis.enqueue_job("run_case_job", tenant, run_id)
                await redis.aclose()
            except Exception:
                # Persisted PENDING work is recovered by the worker's DB scan.
                return
        elif settings.queue_mode == "inline":
            await coordinator.run(tenant, run_id)
        else:

            async def execute():
                try:
                    await coordinator.run(tenant, run_id)
                except Exception:
                    pass  # sanitized error_class is already persisted

            task = asyncio.create_task(execute())
            pending.add(task)
            task.add_done_callback(pending.discard)

    @app.get("/api/health")
    def health():
        try:
            ok = db.ping()
        except Exception:
            ok = False
        return JSONResponse({"status": "ok" if ok else "unavailable", "database": ok}, status_code=200 if ok else 503)

    @app.get("/api/me")
    def me(user=Depends(actor)):
        return user

    @app.get("/api/cases")
    def cases(
        q: str = "",
        status: str | None = None,
        tag: str | None = None,
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
        user=Depends(actor),
    ):
        return service.list(user["tenant_id"], q, status, tag, limit, offset)

    @app.post("/api/cases", status_code=201)
    def create(body: CreateCase, user=Depends(actor), key=Depends(idem)):
        return service.create(user, body, key)

    @app.post("/api/cases/import", status_code=201)
    async def upload(file: UploadFile = File(), user=Depends(actor), key=Depends(idem)):
        name = file.filename or ""
        if not name.lower().endswith((".eml", ".txt")):
            raise ServiceError("Only .eml and .txt imports are accepted; attachments stay quarantined", 415)
        raw = await file.read(settings.max_upload_bytes + 1)
        if len(raw) > settings.max_upload_bytes:
            raise ServiceError("Upload exceeds limit", 413)
        if b"\0" in raw:
            raise ServiceError("Binary/executable upload rejected", 415)
        text = raw.decode("utf-8", errors="replace")
        return service.create(
            user,
            CreateCase(
                title=name[:300], raw_content=text, source_type="eml" if name.lower().endswith(".eml") else "text"
            ),
            key,
            raw_bytes=raw,
        )

    @app.get("/api/cases/{case_id}")
    def case(case_id: str, user=Depends(actor)):
        return service.get(user["tenant_id"], case_id)

    @app.patch("/api/cases/{case_id}")
    async def metadata(case_id: str, body: CaseMetadata, user=Depends(actor)):
        result = service.update_metadata(user, case_id, body)
        if result["workflow_run_id"]:
            await wake(user["tenant_id"], result["workflow_run_id"])
        return service.get(user["tenant_id"], case_id)

    @app.get("/api/cases/{case_id}/related")
    def related(case_id: str, user=Depends(actor)):
        return service.related(user["tenant_id"], case_id)

    @app.post("/api/cases/{case_id}/close")
    def close(case_id: str, body: CloseCase, user=Depends(actor)):
        return service.close(user, case_id, body.case_version)

    @app.post("/api/cases/{case_id}/run")
    async def run(case_id: str, user=Depends(actor)):
        row = coordinator.request(user, case_id)
        await wake(user["tenant_id"], row["id"])
        return {"workflow_run_id": row["id"], "status": service.get(user["tenant_id"], case_id)["status"]}

    @app.get("/api/cases/{case_id}/tasks")
    def tasks(case_id: str, user=Depends(actor)):
        return service.rows(user["tenant_id"], case_id, m.Task)

    @app.get("/api/cases/{case_id}/agent-runs")
    def agents(case_id: str, user=Depends(actor)):
        return service.rows(user["tenant_id"], case_id, m.AgentRun)

    @app.post("/api/cases/{case_id}/tasks/{task_id}/retry")
    async def retry(case_id: str, task_id: str, user=Depends(actor)):
        service.require(user, "admin", "operator", "reviewer")
        service.get(user["tenant_id"], case_id)
        manager = TaskManager(db)
        task = manager.get(user["tenant_id"], task_id)
        if task.case_id != case_id:
            raise ServiceError("Resource not found", 404)
        manager.retry(user["tenant_id"], task_id)
        row = coordinator.request(user, case_id)
        await wake(user["tenant_id"], row["id"])
        return {"status": "READY"}

    @app.get("/api/cases/{case_id}/review-inputs")
    def review_template(case_id: str, user=Depends(actor)):
        service.require(user, "admin", "reviewer")
        return ReviewInputsService(service).template(user["tenant_id"], case_id)

    @app.post("/api/cases/{case_id}/review-inputs")
    def review_inputs(case_id: str, body: ReviewInputs, user=Depends(actor), key=Depends(idem)):
        return ReviewInputsService(service).submit(user, case_id, body, key)

    @app.post("/api/cases/{case_id}/sources")
    def import_source(case_id: str, body: SourceInput, user=Depends(actor), key=Depends(idem)):
        return SourceIntakeService(service).submit(user, case_id, body, key)

    @app.get("/api/cases/{case_id}/evidence")
    def evidence(case_id: str, user=Depends(actor)):
        return service.evidence(user["tenant_id"], case_id)

    @app.get("/api/cases/{case_id}/sources/{source_id}/snapshot")
    def snapshot(case_id: str, source_id: str, user=Depends(actor)):
        return Response(
            service.source_body(user["tenant_id"], case_id, source_id),
            media_type="text/plain",
            headers={"Content-Security-Policy": "default-src 'none'; sandbox"},
        )

    @app.get("/api/cases/{case_id}/risks")
    def risks(case_id: str, user=Depends(actor)):
        return [
            row for row in service.rows(user["tenant_id"], case_id, m.RiskFinding) if row["data"].get("active", True)
        ]

    @app.get("/api/cases/{case_id}/artifacts")
    def artifacts(case_id: str, user=Depends(actor)):
        return service.artifacts(user["tenant_id"], case_id)

    @app.patch("/api/cases/{case_id}/draft")
    async def edit(case_id: str, body: EditDraft, user=Depends(actor)):
        result = service.edit_draft(user, case_id, body)
        case = service.get(user["tenant_id"], case_id)
        if case["workflow_run_id"]:
            await wake(user["tenant_id"], case["workflow_run_id"])
        return result

    @app.get("/api/approvals")
    def approvals(user=Depends(actor)):
        return service.approvals(user["tenant_id"])

    @app.post("/api/approvals/{approval_id}/decide")
    async def decide(approval_id: str, body: Decision, user=Depends(actor), key=Depends(idem)):
        result = service.decide(user, approval_id, body, key)
        case = service.get(user["tenant_id"], result["case_id"])
        if result["action_scope"] == "draft_review" and case["workflow_run_id"]:
            await wake(user["tenant_id"], case["workflow_run_id"])
        return result

    @app.get("/api/follow-ups")
    def followups(user=Depends(actor)):
        return service.followups(user["tenant_id"])

    @app.post("/api/cases/{case_id}/follow-ups")
    def followup(case_id: str, body: FollowUpInput, user=Depends(actor), key=Depends(idem)):
        return service.add_followup(user, case_id, body, key)

    @app.post("/api/follow-ups/{identity}/complete")
    def complete(identity: str, user=Depends(actor)):
        return service.update_followup(user, identity, complete=True)

    @app.patch("/api/follow-ups/{identity}")
    def postpone(identity: str, body: Postpone, user=Depends(actor)):
        return service.update_followup(user, identity, due_at=body.due_at, version=body.version)

    @app.get("/api/cases/{case_id}/events")
    async def events(
        case_id: str,
        request: Request,
        format: str = "sse",
        after: int = Query(0, ge=0),
        last_event_id: str = Header(default=""),
        user=Depends(actor),
    ):
        tenant = user["tenant_id"]
        service.get(tenant, case_id)
        cursor = after
        if last_event_id:
            if not last_event_id.isdigit():
                raise ServiceError("Last-Event-ID must be an event sequence", 422)
            cursor = max(cursor, int(last_event_id))
        if format == "json":
            return service.events(tenant, case_id, cursor)

        async def stream():
            nonlocal cursor
            for _ in range(60):
                if await request.is_disconnected():
                    break
                try:
                    service.authenticate(request.headers.get("authorization", "")[7:])
                except ServiceError:
                    break
                rows = service.events(tenant, case_id, cursor)
                for row in rows:
                    cursor = row["sequence"]
                    yield f"id: {cursor}\nevent: case_event\ndata: {json.dumps(jsonable_encoder(row))}\n\n"
                yield ": heartbeat\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    @app.get("/api/cases/{case_id}/export")
    def export(case_id: str, format: str = "markdown", user=Depends(actor)):
        case = service.get(user["tenant_id"], case_id)
        artifacts = service.artifacts(user["tenant_id"], case_id)
        if format == "json":
            return {"case": case, "evidence": service.evidence(user["tenant_id"], case_id), "artifacts": artifacts}
        report = next((a["content"] for a in reversed(artifacts) if a["kind"] == "report"), "Report not ready")
        if format == "markdown":
            return Response(
                report,
                media_type="text/markdown",
                headers={"Content-Disposition": f'attachment; filename="{case_id}.md"'},
            )
        if format == "pdf":
            import textwrap

            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import Preformatted, SimpleDocTemplate

            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer)
            text = "\n".join(textwrap.fill(line, 85) for line in report.splitlines())
            doc.build([Preformatted(text, getSampleStyleSheet()["Code"])])
            return Response(
                buffer.getvalue(),
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{case_id}.pdf"'},
            )
        raise ServiceError("Unsupported export format", 422)

    @app.get("/api/knowledge")
    def knowledge(user=Depends(actor)):
        return KnowledgeService(service).list(user["tenant_id"])

    @app.post("/api/knowledge")
    def add_knowledge(body: KnowledgeInput, user=Depends(actor)):
        return KnowledgeService(service).put(user, body)

    @app.get("/api/knowledge/{identity}/{version}")
    def knowledge_version(identity: str, version: int, user=Depends(actor)):
        return KnowledgeService(service).get(user["tenant_id"], identity, version)

    @app.get("/api/settings")
    def get_settings(user=Depends(actor)):
        return {
            "runtime": settings.runtime,
            "model": settings.model or "not configured",
            "demo_enabled": settings.demo_enabled,
            "outbound_enabled": settings.outbound_enabled,
            "mail_connector": settings.mail_connector,
            "max_case_seconds": settings.max_case_seconds,
            "max_upload_bytes": settings.max_upload_bytes,
            "queue_mode": settings.queue_mode,
            "sources": [
                {
                    "name": row["name"],
                    "status": "available" if row["available"] else "not_connected",
                    "reason": row.get("unavailable_reason", ""),
                    "license_status": row["license_status"],
                }
                for row in coordinator.host.registry.status()
            ]
            + [
                {"name": "email_import", "status": "manual_import_only", "reason": "Mailbox account not connected"},
                {"name": "crm", "status": "not_connected", "reason": "No authorized live CRM connector"},
            ],
            "max_case_cost_usd": settings.max_case_cost_usd,
            "public_fetch_enabled": settings.public_fetch_enabled,
            "research_domains": list(settings.research_domains),
            "retention": "Operator-managed; encrypted backups and storage lifecycle policy required",
            "roles": ["admin", "reviewer", "operator", "viewer"],
        }

    @app.get("/api/metrics")
    def metrics(user=Depends(actor)):
        service.require(user, "admin")
        return service.metrics(user["tenant_id"])

    @app.post("/api/cases/{case_id}/send-approval")
    def send_approval(case_id: str, body: SendApproval, user=Depends(actor)):
        return outbox.request_approval(user, case_id, body)

    @app.post("/api/cases/{case_id}/outbound-actions")
    def send(case_id: str, body: SendRequest, user=Depends(actor), key=Depends(idem)):
        row = outbox.enqueue(user, case_id, body, key)
        return outbox.dispatch(user["tenant_id"], row["id"])

    @app.get("/api/cases/{case_id}/outbound-actions")
    def outbound(case_id: str, user=Depends(actor)):
        return service.rows(user["tenant_id"], case_id, m.OutboundAction)

    @app.post("/api/outbound-actions/{identity}/reconcile")
    def reconcile(identity: str, body: Reconciliation, user=Depends(actor)):
        return outbox.reconcile(user, identity, body.receipt, body.delivered)

    @app.post("/api/outbound-actions/{identity}/cancel")
    def cancel_action(identity: str, body: CancelAction, user=Depends(actor)):
        return outbox.cancel(user, identity, body.case_version, body.reason)

    return app
