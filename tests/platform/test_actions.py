import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from test_api import api as api
from test_api import create_run

from tradecase.platform.actions import FakeMail, OutboxService
from tradecase.platform.contracts import Decision
from tradecase.platform.services import ServiceError


def approved_action(api, connector=None):
    client, app, headers, *_ = api
    case_id = create_run(api)
    service = app.state.service
    actor = service.authenticate(headers["Authorization"][7:])
    approval = service.approvals(actor["tenant_id"])[0]
    service.decide(
        actor,
        approval["id"],
        Decision(decision="approve", artifact_hash=approval["artifact_hash"], case_version=approval["case_version"]),
        "draft-review",
    )
    draft = next(
        json.loads(x["content"]) for x in service.artifacts(actor["tenant_id"], case_id) if x["kind"] == "draft"
    )
    mail = connector or FakeMail()
    outbox = OutboxService(service, mail)
    send = outbox.request_approval(
        actor,
        case_id,
        SimpleNamespace(
            target=draft["recipient_email"],
            channel="mail",
            case_version=approval["case_version"],
            artifact_hash=approval["artifact_hash"],
        ),
    )
    service.decide(
        actor,
        send["id"],
        Decision(decision="approve", artifact_hash=send["artifact_hash"], case_version=send["case_version"]),
        "send-review",
    )
    request = SimpleNamespace(
        approval_id=send["id"], artifact_hash=send["artifact_hash"], case_version=send["case_version"]
    )
    service.settings.outbound_enabled = True
    return outbox, actor, case_id, request, mail


def test_sandbox_receipt_and_concurrent_duplicate_delivery(api):
    outbox, actor, case_id, request, mail = approved_action(api)
    row = outbox.enqueue(actor, case_id, request, "send-1")
    assert outbox.enqueue(actor, case_id, request, "different-key")["id"] == row["id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: outbox.dispatch(actor["tenant_id"], row["id"]), range(2)))
    assert len(mail.calls) == 1
    assert outbox.dispatch(actor["tenant_id"], row["id"])["status"] == "SANDBOX_ACCEPTED"
    assert all(r["status"] in {"DISPATCHING", "SANDBOX_ACCEPTED"} for r in results)


def test_uncertain_outcome_never_replayed(api):
    outbox, actor, case_id, request, mail = approved_action(api, FakeMail(uncertain=True))
    row = outbox.enqueue(actor, case_id, request, "uncertain")
    assert outbox.dispatch(actor["tenant_id"], row["id"])["status"] == "DELIVERY_UNCERTAIN"
    assert outbox.dispatch(actor["tenant_id"], row["id"])["receipt"]["retry_allowed"] is False
    assert len(mail.calls) == 1
    result = outbox.reconcile(actor, row["id"], "Sandbox provider reconciliation receipt", False)
    assert result["status"] == "RECONCILED_NOT_DELIVERED"
    assert outbox.dispatch(actor["tenant_id"], row["id"])["status"] == "RECONCILED_NOT_DELIVERED"
    assert len(mail.calls) == 1


def test_edit_after_enqueue_invalidates_at_dispatch(api):
    outbox, actor, case_id, request, mail = approved_action(api)
    row = outbox.enqueue(actor, case_id, request, "queued")
    from tradecase.platform.contracts import EditDraft

    outbox.service.edit_draft(
        actor,
        case_id,
        EditDraft(body="Please clarify quantity.", subject="Clarification", case_version=request.case_version),
    )
    with pytest.raises(ServiceError, match="stale"):
        outbox.dispatch(actor["tenant_id"], row["id"])
    assert mail.calls == []


def test_scope_and_synthetic_live_provider_gate(api):
    outbox, actor, case_id, request, mail = approved_action(api)
    mail.is_sandbox = False
    with pytest.raises(ServiceError, match="Synthetic"):
        outbox.enqueue(actor, case_id, request, "live")
    assert mail.calls == []


def test_inflight_delivery_freezes_draft_and_reconciliation(api):
    from threading import Event

    from tradecase.platform.contracts import EditDraft

    entered, release = Event(), Event()

    class BlockingMail(FakeMail):
        def send(self, **kwargs):
            entered.set()
            assert release.wait(5)
            return super().send(**kwargs)

    outbox, actor, case_id, request, mail = approved_action(api, BlockingMail())
    row = outbox.enqueue(actor, case_id, request, "racing")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(outbox.dispatch, actor["tenant_id"], row["id"])
        assert entered.wait(5)
        try:
            with pytest.raises(ServiceError, match="finish or be reconciled"):
                outbox.service.edit_draft(
                    actor, case_id, EditDraft(body="Changed.", subject="Changed", case_version=request.case_version)
                )
            with pytest.raises(ServiceError, match="still be active"):
                outbox.reconcile(actor, row["id"], "premature", False)
        finally:
            release.set()
        assert future.result()["status"] == "SANDBOX_ACCEPTED"
    assert len(mail.calls) == 1


def test_send_authorization_requires_current_approved_draft_review(api):
    client, app, headers, *_ = api
    case_id = create_run(api)
    approval = client.get("/api/approvals", headers=headers).json()[0]
    draft = next(
        json.loads(item["content"])
        for item in client.get(f"/api/cases/{case_id}/artifacts", headers=headers).json()
        if item["kind"] == "draft"
    )
    response = client.post(
        f"/api/cases/{case_id}/send-approval",
        headers=headers,
        json={
            "case_version": approval["case_version"],
            "artifact_hash": approval["artifact_hash"],
            "channel": "mail",
            "target": draft["recipient_email"],
        },
    )
    assert response.status_code == 403
    assert "draft review" in response.text


@pytest.mark.parametrize("decision", ["reject", "request_changes", "request_evidence"])
def test_negative_review_revokes_legacy_send_before_delayed_worker(api, decision):
    from unittest.mock import AsyncMock, patch

    from sqlalchemy import select

    from tradecase.platform import db as m

    client, app, headers, *_ = api
    outbox, actor, case_id, request, mail = approved_action(api)
    row = outbox.enqueue(actor, case_id, request, "queued-before-review")
    # Represent pre-upgrade authorizations, which could coexist with a pending
    # draft review. New authorization admission no longer permits this state.
    with outbox.db.session() as session:
        review = session.scalar(
            select(m.Approval).where(m.Approval.case_id == case_id, m.Approval.action_scope == "draft_review")
        )
        review.status, review.decision, review.idempotency_key = "PENDING", None, None
        review_id = review.id
    with patch.object(app.state.coordinator, "run", new=AsyncMock(return_value=None)):
        response = client.post(
            f"/api/approvals/{review_id}/decide",
            headers={**headers, "Idempotency-Key": "negative-review"},
            json={"decision": decision, "artifact_hash": request.artifact_hash, "case_version": request.case_version},
        )
    assert response.status_code == 200, response.text
    send = next(a for a in outbox.service.approvals(actor["tenant_id"]) if a["id"] == request.approval_id)
    assert send["status"] == "INVALIDATED"
    with pytest.raises(ServiceError):
        outbox.dispatch(actor["tenant_id"], row["id"])
    with pytest.raises(ServiceError, match="draft review"):
        outbox.request_approval(
            actor,
            case_id,
            SimpleNamespace(
                target=send["data"]["target"],
                channel="mail",
                case_version=request.case_version,
                artifact_hash=request.artifact_hash,
            ),
        )
    assert mail.calls == []


@pytest.mark.parametrize("status", ["DISPATCHING", "DELIVERY_UNCERTAIN"])
def test_legacy_pending_review_cannot_mutate_inflight_delivery(api, status):
    from sqlalchemy import select

    from tradecase.platform import db as m

    client, app, headers, *_ = api
    outbox, actor, case_id, request, mail = approved_action(api)
    row = outbox.enqueue(actor, case_id, request, "legacy-inflight")
    with outbox.db.session() as session:
        review = session.scalar(
            select(m.Approval).where(m.Approval.case_id == case_id, m.Approval.action_scope == "draft_review")
        )
        review.status, review.decision, review.idempotency_key = "PENDING", None, None
        review_id = review.id
        session.get(m.OutboundAction, row["id"]).status = status
    response = client.post(
        f"/api/approvals/{review_id}/decide",
        headers={**headers, "Idempotency-Key": "concurrent-changes"},
        json={
            "decision": "request_changes",
            "artifact_hash": request.artifact_hash,
            "case_version": request.case_version,
        },
    )
    assert response.status_code == 409, response.text
    assert "finish or be reconciled" in response.text
    assert client.get(f"/api/cases/{case_id}", headers=headers).json()["version"] == request.case_version
    assert mail.calls == []


def test_stale_queued_action_can_be_cancelled_without_dispatch(api):
    from tradecase.platform.contracts import EditDraft

    client, app, headers, *_ = api
    outbox, actor, case_id, request, mail = approved_action(api)
    row = outbox.enqueue(actor, case_id, request, "stale-cancel")
    edit = outbox.service.edit_draft(
        actor, case_id, EditDraft(body="Please clarify quantity.", subject="Review", case_version=request.case_version)
    )
    payload = {"case_version": edit["case_version"], "reason": "Superseded draft"}
    url = f"/api/outbound-actions/{row['id']}/cancel"
    assert client.post(url, headers=headers, json={**payload, "case_version": request.case_version}).status_code == 409
    response = client.post(url, headers=headers, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "CANCELLED"
    assert client.post(url, headers=headers, json=payload).json()["id"] == row["id"]
    assert outbox.dispatch(actor["tenant_id"], row["id"])["status"] == "CANCELLED"
    assert mail.calls == []


def test_close_cancels_queued_actions(api):
    outbox, actor, case_id, request, mail = approved_action(api)
    row = outbox.enqueue(actor, case_id, request, "close-queued")
    outbox.service.close(actor, case_id, request.case_version)
    assert outbox.dispatch(actor["tenant_id"], row["id"])["status"] == "CANCELLED"
    assert mail.calls == []


def test_cannot_cancel_uncertain_delivery(api):
    outbox, actor, case_id, request, mail = approved_action(api, FakeMail(uncertain=True))
    row = outbox.enqueue(actor, case_id, request, "uncertain-cancel")
    outbox.dispatch(actor["tenant_id"], row["id"])
    with pytest.raises(ServiceError, match="Only a queued"):
        outbox.cancel(actor, row["id"], request.case_version, "Cannot know whether sent")
    with pytest.raises(ServiceError, match="finish or be reconciled"):
        outbox.service.close(actor, case_id, request.case_version)
    assert len(mail.calls) == 1
