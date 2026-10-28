import json

import pytest
from fastapi.testclient import TestClient

from tradecase.platform.api import create_app
from tradecase.platform.config import Settings
from tradecase.platform.db import Database


@pytest.fixture
def api(tmp_path):
    tmp_path = tmp_path.resolve()
    settings = Settings(
        database_url="sqlite:///" + str(tmp_path / "db.sqlite"),
        storage_root=tmp_path / "objects",
        work_root=tmp_path / "work",
        checkpoint_url="sqlite:///" + str(tmp_path / "checkpoint.sqlite"),
        demo_enabled=True,
        queue_mode="inline",
    )
    db = Database(settings.database_url)
    db.create_schema()
    app = create_app(settings, db)
    _, token = app.state.service.provision("alpha", "Reviewer")
    _, other = app.state.service.provision("beta", "Other")
    _, viewer = app.state.service.provision("alpha", "Viewer", "viewer")
    with TestClient(app) as client:
        yield (
            client,
            app,
            {"Authorization": "Bearer " + token, "Idempotency-Key": "case-1"},
            {"Authorization": "Bearer " + other},
            {"Authorization": "Bearer " + viewer},
        )
    db.close()


def create_run(api, fixture="case_strong"):
    client, app, headers, other, viewer = api
    response = client.post("/api/cases", headers=headers, json={"title": "Synthetic inquiry", "fixture": fixture})
    assert response.status_code == 201, response.text
    identity = response.json()["id"]
    response = client.post(f"/api/cases/{identity}/run", headers=headers)
    assert response.status_code == 200, response.text
    return identity


def test_case_approval_followup_exports_and_idempotence(api):
    client, app, headers, *_ = api
    case_id = create_run(api)
    case = client.get(f"/api/cases/{case_id}", headers=headers).json()
    assert case["status"] == "NEEDS_REVIEW"
    evidence = client.get(f"/api/cases/{case_id}/evidence", headers=headers).json()
    assert evidence["claims"] and evidence["sources"]
    snapshot = client.get(evidence["sources"][0]["snapshot_url"], headers=headers)
    assert snapshot.status_code == 200 and "SYNTHETIC" in snapshot.text
    approval = client.get("/api/approvals", headers=headers).json()[0]
    payload = {
        "decision": "approve",
        "artifact_hash": approval["artifact_hash"],
        "case_version": approval["case_version"],
    }
    decision_headers = {**headers, "Idempotency-Key": "review-1"}
    response = client.post("/api/approvals/" + approval["id"] + "/decide", headers=decision_headers, json=payload)
    assert response.status_code == 200, response.text
    assert (
        client.post("/api/approvals/" + approval["id"] + "/decide", headers=decision_headers, json=payload).status_code
        == 200
    )
    assert client.get(f"/api/cases/{case_id}", headers=headers).json()["status"] == "READY_TO_FOLLOW_UP"
    followups = client.get("/api/follow-ups", headers=headers).json()
    assert len(followups) == 1
    assert (
        client.post("/api/follow-ups/" + followups[0]["id"] + "/complete", headers=headers).json()["status"]
        == "COMPLETED"
    )
    for fmt in ["json", "markdown", "pdf"]:
        result = client.get(f"/api/cases/{case_id}/export?format={fmt}", headers=headers)
        assert result.status_code == 200, result.text
        if fmt == "pdf":
            assert result.content.startswith(b"%PDF")
    assert client.post(f"/api/cases/{case_id}/run", headers=headers).status_code == 200
    assert len(client.get("/api/follow-ups", headers=headers).json()) == 1


def test_tenant_and_roles(api):
    client, app, headers, other, viewer = api
    case_id = create_run(api)
    for endpoint in ["", "/evidence", "/tasks", "/risks", "/artifacts", "/events?format=json", "/export"]:
        assert client.get("/api/cases/" + case_id + endpoint, headers=other).status_code == 404
    assert client.get("/api/cases", headers=other).json() == []
    assert client.get("/api/approvals", headers=other).json() == []
    assert client.get("/api/cases").status_code == 401
    assert (
        client.post(
            "/api/cases", headers={**viewer, "Idempotency-Key": "new"}, json={"raw_content": "hello"}
        ).status_code
        == 403
    )
    assert client.get("/api/metrics", headers=viewer).status_code == 403


def test_idempotency_mismatch_and_stale_draft(api):
    client, app, headers, *_ = api
    case_id = create_run(api)
    assert client.post("/api/cases", headers=headers, json={"raw_content": "different"}).status_code == 409
    approval = client.get("/api/approvals", headers=headers).json()[0]
    version = approval["case_version"]
    edited = client.patch(
        f"/api/cases/{case_id}/draft",
        headers=headers,
        json={"body": "Thank you. Please confirm quantity.", "subject": "Inquiry response", "case_version": version},
    )
    assert edited.status_code == 200, edited.text
    stale = client.post(
        "/api/approvals/" + approval["id"] + "/decide",
        headers={**headers, "Idempotency-Key": "old-review"},
        json={"decision": "approve", "artifact_hash": approval["artifact_hash"], "case_version": version},
    )
    assert stale.status_code == 409, stale.text
    assert (
        client.patch(
            f"/api/cases/{case_id}/draft",
            headers=headers,
            json={"body": "Again", "subject": "Again", "case_version": version},
        ).status_code
        == 409
    )


@pytest.mark.parametrize("decision,status", [("reject", "NEEDS_INPUT"), ("request_evidence", "NEEDS_INPUT")])
def test_negative_decision_resumes(api, decision, status):
    client, app, headers, *_ = api
    case_id = create_run(api)
    approval = client.get("/api/approvals", headers=headers).json()[0]
    response = client.post(
        "/api/approvals/" + approval["id"] + "/decide",
        headers={**headers, "Idempotency-Key": "decision"},
        json={
            "decision": decision,
            "artifact_hash": approval["artifact_hash"],
            "case_version": approval["case_version"],
        },
    )
    assert response.status_code == 200, response.text
    assert client.get("/api/cases/" + case_id, headers=headers).json()["status"] == status


def test_real_input_is_partial_and_no_fabricated_evidence(api):
    client, app, headers, *_ = api
    response = client.post(
        "/api/cases",
        headers=headers,
        json={"raw_content": "Please quote widgets for France.", "buyer_email": "buyer@example.org"},
    )
    case_id = response.json()["id"]
    response = client.post(f"/api/cases/{case_id}/run", headers=headers)
    assert response.status_code == 200, response.text
    case = client.get("/api/cases/" + case_id, headers=headers).json()
    assert case["research_status"] == "PARTIAL" and not case["synthetic"]
    assert client.get(f"/api/cases/{case_id}/evidence", headers=headers).json()["claims"] == []
    assert len(client.get(f"/api/cases/{case_id}/risks", headers=headers).json()) == 2


def test_upload_limits_and_active_content(api):
    client, app, headers, *_ = api
    assert client.post("/api/cases/import", headers=headers, files={"file": ("bad.exe", b"MZbad")}).status_code == 415
    response = client.post(
        "/api/cases/import",
        headers=headers,
        files={
            "file": ("inquiry.eml", b"From: buyer@example.org\nContent-Type: text/html\n\n<script>send mail</script>")
        },
    )
    assert response.status_code == 201, response.text
    assert "<script>" in response.json()["inquiry"]["buyer_message"]
    assert (
        client.post(
            "/api/cases", headers={**headers, "Content-Length": "3000000"}, json={"raw_content": "x"}
        ).status_code
        == 413
    )


def test_default_outbound_off_and_redacted_events(api):
    client, app, headers, *_ = api
    case_id = create_run(api)
    approval = client.get("/api/approvals", headers=headers).json()[0]
    response = client.post(
        f"/api/cases/{case_id}/outbound-actions",
        headers=headers,
        json={
            "approval_id": approval["id"],
            "artifact_hash": approval["artifact_hash"],
            "case_version": approval["case_version"],
        },
    )
    assert response.status_code == 403
    events = client.get(f"/api/cases/{case_id}/events?format=json", headers=headers).json()
    assert len({e["sequence"] for e in events}) == len(events)
    assert "purchasing@" not in json.dumps(events)
    tail = client.get(
        f"/api/cases/{case_id}/events?format=json", headers={**headers, "Last-Event-ID": str(events[-2]["sequence"])}
    ).json()
    assert [e["sequence"] for e in tail] == [events[-1]["sequence"]]


def test_chunked_request_limit_without_content_length(api):
    client, app, headers, *_ = api
    chunks = (b"x" * 65536 for _ in range(40))
    response = client.post("/api/cases", headers={**headers, "Content-Type": "application/json"}, content=chunks)
    assert response.status_code == 413


def test_metadata_related_and_search(api):
    client, app, headers, *_ = api
    case_id = create_run(api)
    case = client.get("/api/cases/" + case_id, headers=headers).json()
    result = client.patch(
        "/api/cases/" + case_id,
        headers=headers,
        json={"case_version": case["version"], "tags": ["priority", "toys"], "priority": 75, "title": "Reviewed buyer"},
    )
    assert result.status_code == 200, result.text
    assert result.json()["tags"] == ["priority", "toys"]
    assert result.json()["status"] == "NEEDS_REVIEW"
    assert any(
        x["status"] == "PENDING" and x["case_version"] == result.json()["version"]
        for x in client.get("/api/approvals", headers=headers).json()
    )
    assert len(client.get("/api/cases?q=harbor&tag=toys", headers=headers).json()) == 1
    second = client.post(
        "/api/cases",
        headers={**headers, "Idempotency-Key": "second"},
        json={"title": "Related", "raw_content": "Follow-up", "buyer_email": "other@harbor-toys.invalid"},
    ).json()
    related = client.get("/api/cases/" + case_id + "/related", headers=headers).json()
    assert related[0]["id"] == second["id"] and related[0]["relation"].endswith("unverified")


def test_close_cancels_waiting_work_and_keeps_history(api):
    client, app, headers, *_ = api
    case_id = create_run(api)
    case = client.get("/api/cases/" + case_id, headers=headers).json()
    result = client.post("/api/cases/" + case_id + "/close", headers=headers, json={"case_version": case["version"]})
    assert result.status_code == 200 and result.json()["status"] == "CLOSED"
    assert not any(
        x["status"] == "WAITING_HUMAN" for x in client.get("/api/cases/" + case_id + "/tasks", headers=headers).json()
    )
    assert client.get("/api/cases/" + case_id + "/artifacts", headers=headers).json()
