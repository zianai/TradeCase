"""Explicitly approved outbox. An uncertain delivery is never automatically retried."""

from __future__ import annotations

import json
import os
import smtplib
import ssl
from datetime import timedelta
from email.message import EmailMessage
from typing import Protocol

from sqlalchemy import select

from tradecase.models import email_address
from tradecase.platform import db as m
from tradecase.platform.services import ServiceError, fingerprint


class DeliveryUncertain(RuntimeError):
    pass


class ActionConnector(Protocol):
    name: str
    is_sandbox: bool

    def send(self, *, action_id: str, target: str, payload: dict) -> dict: ...


class FakeMail:
    name = "fake_mail"
    is_sandbox = True

    def __init__(self, uncertain=False):
        self.calls = []
        self.uncertain = uncertain

    def send(self, *, action_id, target, payload):
        self.calls.append(action_id)
        if self.uncertain:
            raise DeliveryUncertain("Sandbox simulated ambiguous delivery")
        return {"provider": "fake_mail", "receipt_id": "sandbox-" + action_id, "sandbox": True, "delivered": False}


class SMTPMail:
    """Explicit opt-in SSL SMTP. Timeout after handoff cannot be distinguished from delivery."""

    name = "smtp"
    is_sandbox = False

    def send(self, *, action_id, target, payload):
        required = ["TRADECASE_SMTP_HOST", "TRADECASE_SMTP_USER", "TRADECASE_SMTP_PASSWORD", "TRADECASE_MAIL_FROM"]
        if not all(os.getenv(k) for k in required):
            raise ServiceError("Mail connector credentials not configured", 503)
        message = EmailMessage()
        message["From"] = email_address(os.environ["TRADECASE_MAIL_FROM"])
        message["To"] = email_address(target)
        message["Subject"] = payload["subject"]
        message["Message-ID"] = f"<tradecase-{action_id}@{message['From'].rsplit('@', 1)[1]}>"
        message.set_content(payload["body_text"])
        try:
            with smtplib.SMTP_SSL(
                os.environ["TRADECASE_SMTP_HOST"],
                int(os.getenv("TRADECASE_SMTP_PORT", "465")),
                timeout=20,
                context=ssl.create_default_context(),
            ) as client:
                client.login(os.environ["TRADECASE_SMTP_USER"], os.environ["TRADECASE_SMTP_PASSWORD"])
                refused = client.send_message(message)
                if refused:
                    raise DeliveryUncertain("Recipient acceptance requires reconciliation")
            return {"provider": "smtp", "message_id": message["Message-ID"], "sandbox": False, "accepted": True}
        except Exception as exc:
            raise DeliveryUncertain("Provider result uncertain: " + type(exc).__name__) from None


class FakeCRM(FakeMail):
    name = "fake_crm"


class OutboxService:
    def __init__(self, service, connector=None):
        self.service = service
        self.db = service.db
        self.connector = connector or (
            FakeMail()
            if service.settings.mail_connector == "fake"
            else SMTPMail()
            if service.settings.mail_connector == "smtp"
            else None
        )

    def request_approval(self, actor, case_id, request):
        self.service.require(actor, "admin", "reviewer")
        target = email_address(request.target) if request.channel == "mail" else request.target
        with self.db.session() as s:
            case = self.service.lock_case(s, actor["tenant_id"], case_id, request.case_version)
            self.service.require_reviewed_draft(s, case)
            version = self.service.current_artifact(s, case.tenant_id, case.id, "draft")
            if version.content_hash != request.artifact_hash:
                raise ServiceError("Draft changed")
            if request.channel == "mail":
                draft = json.loads(self.service.storage.get(version.storage_ref))
                if target != draft.get("recipient_email"):
                    raise ServiceError("Target must match the versioned draft recipient")
            scope = "mail_send" if request.channel == "mail" else "crm_sync"
            approval = self.service.prepare_approval(s, case, scope, {"target": target, "channel": request.channel})
            if approval.data.get("target") != target:
                raise ServiceError("Approval already binds a different target")
            return m.row_dict(approval)

    def enqueue(self, actor, case_id, request, key):
        self.service.require(actor, "admin", "reviewer")
        if not self.service.settings.outbound_enabled:
            raise ServiceError("External writes are disabled; use manual follow-up", 403)
        if self.connector is None:
            raise ServiceError("Connector unavailable; use manual follow-up", 503)
        with self.db.session() as s:
            case = self.service.lock_case(s, actor["tenant_id"], case_id, request.case_version)
            approval = self.service.scoped(s, m.Approval, case.tenant_id, request.approval_id)
            version = self.service.validate_approval(s, case, approval, "mail_send")
            self.service.require_reviewed_draft(s, case)
            if approval.status != "APPROVED" or approval.decision != "approved":
                raise ServiceError("Explicit send approval required", 403)
            if request.artifact_hash != version.content_hash:
                raise ServiceError("Draft changed")
            if (
                not case.data.get("quality_passed")
                or case.data.get("unresolved_risks")
                or case.data.get("research_status") != "COMPLETE"
            ):
                raise ServiceError("Unresolved evidence/quality/risk gate blocks sending")
            if case.data.get("synthetic") and not self.connector.is_sandbox:
                raise ServiceError("Synthetic Cases cannot be sent to live providers", 403)
            target = approval.data["target"]
            logical = fingerprint([case.id, version.content_hash, target, "mail"])
            existing = s.scalar(
                select(m.OutboundAction).where(
                    m.OutboundAction.tenant_id == case.tenant_id, m.OutboundAction.idempotency_key == key
                )
            )
            if existing:
                if existing.logical_fingerprint != logical:
                    raise ServiceError("Idempotency payload mismatch")
                return m.row_dict(existing)
            existing = s.scalar(
                select(m.OutboundAction).where(
                    m.OutboundAction.tenant_id == case.tenant_id,
                    m.OutboundAction.case_id == case_id,
                    m.OutboundAction.logical_fingerprint == logical,
                )
            )
            if existing:
                return m.row_dict(existing)
            row = m.OutboundAction(
                id=m.uid(),
                tenant_id=case.tenant_id,
                case_id=case_id,
                approval_id=approval.id,
                artifact_hash=version.content_hash,
                idempotency_key=key,
                logical_fingerprint=logical,
                target=target,
                data={"case_version": case.version, "artifact_version_id": version.id, "requested_by": actor["id"]},
            )
            s.add(row)
            s.flush()
            self.service.event(s, case.tenant_id, case_id, "outbound.queued", {"action_id": row.id}, actor=actor["id"])
            return m.row_dict(row)

    def dispatch(self, tenant, action_id):
        if not self.service.settings.outbound_enabled or self.connector is None:
            raise ServiceError("Outbound connector disabled", 403)
        with self.db.session() as s:
            row = self.service.scoped(s, m.OutboundAction, tenant, action_id)
            case = self.service.lock_case(s, tenant, row.case_id)
            s.refresh(row)
            if row.status != "PENDING":
                return m.row_dict(row)
            approval = self.service.scoped(s, m.Approval, tenant, row.approval_id)
            version = self.service.validate_approval(s, case, approval, "mail_send")
            self.service.require_reviewed_draft(s, case)
            if approval.status != "APPROVED":
                raise ServiceError("Approval revoked", 403)
            if (
                not case.data.get("quality_passed")
                or case.data.get("unresolved_risks")
                or case.data.get("research_status") != "COMPLETE"
            ):
                raise ServiceError("Case no longer satisfies external-write gates")
            if case.data.get("synthetic") and not self.connector.is_sandbox:
                raise ServiceError("Synthetic data cannot go to live provider", 403)
            payload = json.loads(self.service.storage.get(version.storage_ref))
            target = row.target
            row.status = "DISPATCHING"
            row.dispatched_at = m.utcnow()
        # Crash after DISPATCHING is uncertain, including before network handoff. Never replay blindly.
        try:
            receipt = self.connector.send(action_id=action_id, target=target, payload=payload)
            status = "SANDBOX_ACCEPTED" if self.connector.is_sandbox else "SENT"
        except Exception as exc:
            receipt = {"error_class": type(exc).__name__, "retry_allowed": False}
            status = "DELIVERY_UNCERTAIN"
        with self.db.session() as s:
            row = self.service.scoped(s, m.OutboundAction, tenant, action_id)
            self.service.lock_case(s, tenant, row.case_id)
            s.refresh(row)
            if row.status != "DISPATCHING":
                row.data = {**row.data, "late_provider_receipt": receipt, "late_provider_status": status}
                self.service.event(
                    s, tenant, row.case_id, "outbound.late_receipt", {"status": status, "action_id": action_id}
                )
                return m.row_dict(row)
            row.status = status
            row.receipt = receipt
            row.finished_at = m.utcnow()
            self.service.event(s, tenant, row.case_id, "outbound.receipt", {"status": status, "action_id": action_id})
            return m.row_dict(row)

    def cancel(self, actor, action_id, case_version, reason):
        self.service.require(actor, "admin", "reviewer")
        with self.db.session() as s:
            row = self.service.scoped(s, m.OutboundAction, actor["tenant_id"], action_id)
            self.service.lock_case(s, row.tenant_id, row.case_id, case_version)
            s.refresh(row)
            if row.status == "CANCELLED":
                return m.row_dict(row)
            if row.status != "PENDING":
                raise ServiceError("Only a queued, undispatched action can be cancelled; reconcile uncertain delivery")
            row.status = "CANCELLED"
            row.finished_at = m.utcnow()
            row.data = {**row.data, "cancelled_by": actor["id"], "cancellation_reason": reason}
            self.service.event(
                s, row.tenant_id, row.case_id, "outbound.cancelled", {"action_id": row.id}, actor=actor["id"]
            )
            return m.row_dict(row)

    def reconcile(self, actor, action_id, receipt, delivered):
        self.service.require(actor, "admin")
        if not receipt.strip():
            raise ServiceError("External receipt evidence is required", 422)
        with self.db.session() as s:
            row = self.service.scoped(s, m.OutboundAction, actor["tenant_id"], action_id)
            self.service.lock_case(s, row.tenant_id, row.case_id)
            s.refresh(row)
            if (
                row.status == "DISPATCHING"
                and row.dispatched_at
                and row.dispatched_at > m.utcnow() - timedelta(minutes=5)
            ):
                raise ServiceError("Dispatch may still be active; reconcile after its five-minute timeout")
            if row.status not in {"DISPATCHING", "DELIVERY_UNCERTAIN"}:
                raise ServiceError("Action is not awaiting reconciliation")
            row.status = "RECONCILED_DELIVERED" if delivered else "RECONCILED_NOT_DELIVERED"
            row.receipt = {
                **(row.receipt or {}),
                "reconciliation": receipt,
                "reviewer": actor["id"],
                "retry_allowed": False,
            }
            self.service.event(
                s, row.tenant_id, row.case_id, "outbound.reconciled", {"status": row.status}, actor=actor["id"]
            )
            return m.row_dict(row)
