"""Synthetic local regressions; no business review or external authorization."""

import hashlib
import json
from datetime import timedelta

import pytest
from sqlalchemy import select
from test_api import api as api
from test_api import create_run

from tradecase.platform import db as m
from tradecase.platform.services import ServiceError


def pilot_payload():
    raw = "SYNTHETIC PILOT ONLY. Please quote widgets. Buyer identity is unknown."
    return {
        "title": "Synthetic P8 pilot", "raw_content": raw, "classification": "synthetic",
        "synthetic": True, "dataset_id": "g0-test", "dataset_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "rights_reference": "SYNTHETIC_TEST_ONLY", "source_locator": "inquiry.txt:line:1",
        "captured_at": (m.utcnow() - timedelta(minutes=1)).isoformat(),
        "retention_until": (m.utcnow() + timedelta(days=1)).isoformat(),
    }


def test_pilot_import_deduplicates_preserves_origin_and_export_is_not_acceptance(api):
    client, app, headers, other, viewer = api
    payload = pilot_payload()
    response = client.post("/api/pilot/cases", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    case = response.json()
    assert case["synthetic"] is True
    assert case["inquiry"]["is_synthetic"] is True
    assert case["data"]["pilot"]["source_locator"] == "inquiry.txt:line:1"
    assert client.post("/api/pilot/cases", headers={**headers, "Idempotency-Key": "retry"}, json=payload).json()["id"] == case["id"]
    card = client.get(f"/api/cases/{case['id']}/pilot-export", headers=headers).json()
    assert card["business_evaluation"] is None and card["human_review_status"] == "pending"
    assert card["input_sha256"] == payload["dataset_sha256"]
    assert "buyer_email" not in card and "raw_content" not in card
    assert client.get(f"/api/cases/{case['id']}/pilot-export", headers=other).status_code == 404
    assert client.post("/api/pilot/cases", headers=viewer, json=payload).status_code == 403


def test_pilot_real_data_requires_independent_grant_before_storage(api):
    client, app, headers, *_ = api
    payload = {**pilot_payload(), "classification": "private_cleared", "synthetic": False}
    before = list(app.state.service.storage.root.rglob("*"))
    response = client.post("/api/pilot/cases", headers=headers, json=payload)
    assert response.status_code == 403 and "BLOCKED_EXTERNAL" in response.text
    assert list(app.state.service.storage.root.rglob("*")) == before
    assert client.get("/api/cases", headers=headers).json() == []


def test_pilot_mismatch_expiry_rights_and_synthetic_laundering_rejected(api):
    client, _, headers, *_ = api
    for updates in [
        {"dataset_sha256": "f" * 64}, {"synthetic": False}, {"rights_reference": ""},
        {"retention_until": (m.utcnow() - timedelta(days=1)).isoformat()},
        {"source_locator": "../../secrets"}, {"classification": "restricted", "synthetic": False},
    ]:
        result = client.post("/api/pilot/cases", headers=headers, json={**pilot_payload(), **updates})
        assert result.status_code in (403, 422), result.text


def test_provenance_exports_conflicts_and_exact_link_locator(api):
    client, app, headers, *_ = api
    case_id = create_run(api, "case_name_collision")
    with app.state.service.db.session() as session:
        case = session.get(m.Case, case_id)
        case.data = {**case.data, "conflicts": [{"reason": "Same name, incompatible address", "status": "unresolved"}]}
        link = session.scalar(select(m.ClaimEvidenceLink).where(m.ClaimEvidenceLink.case_id == case_id))
        link.locator = "snapshot.txt:line:2"
        link.relation = "contradicts"
    evidence = client.get(f"/api/cases/{case_id}/evidence", headers=headers).json()
    assert evidence["conflicts"][0]["status"] == "unresolved"
    card = client.get(f"/api/cases/{case_id}/pilot-export", headers=headers).json()
    assert card["case_version"] == evidence["case_version"]
    assert any(x["locator"] == "snapshot.txt:line:2" and x["relation"] == "contradicts" for x in card["citations"])
    assert len(card["subject_sha256"]) == 64
    assert card["business_evaluation"] is None
    assert card["external_send_authorized"] is False


def test_source_intake_precise_locator_expiration_and_approval_invalidation(api):
    client, app, headers, *_ = api
    case_id = create_run(api)
    before = client.get(f"/api/cases/{case_id}", headers=headers).json()
    old = client.get("/api/approvals", headers=headers).json()[0]
    response = client.post(f"/api/cases/{case_id}/sources", headers={**headers, "Idempotency-Key": "expired"}, json={
        "case_version": before["version"], "url": "https://procurement.example.org/notice",
        "title": "Synthetic expired procurement notice", "captured_at": (m.utcnow()-timedelta(days=10)).isoformat(),
        "text": "SYNTHETIC. Deadline was yesterday.", "excerpt": "Deadline was yesterday.",
        "claim": "The procurement is currently open.", "locator": "notice:line:1",
        "relation": "contradicts", "expires_at": (m.utcnow()-timedelta(days=1)).isoformat(),
    })
    assert response.status_code == 200, response.text
    evidence = client.get(f"/api/cases/{case_id}/evidence", headers=headers).json()
    imported = next(x for x in evidence["sources"] if x["id"] == response.json()["source_id"])
    assert imported["current_validity"] == "expired"
    assert any(x["locator"] == "notice:line:1" for x in evidence["links"])
    current = client.get("/api/approvals", headers=headers).json()
    assert next(x for x in current if x["id"] == old["id"])["status"] == "INVALIDATED"


def test_same_name_injection_unknown_sources_never_unlock_send(api):
    client, _, headers, *_ = api
    for fixture in ["case_name_collision", "case_prompt_injection", "case_regulation_unknown", "case_inferred_email"]:
        local = (client, api[1], {**headers, "Idempotency-Key": fixture}, *api[3:])
        case_id = create_run(local, fixture)
        case = client.get(f"/api/cases/{case_id}", headers=headers).json()
        assert not case["outbound_enabled"]
        assert client.get(f"/api/cases/{case_id}/outbound-actions", headers=headers).json() == []
        assert client.get(f"/api/cases/{case_id}/pilot-export", headers=headers).json()["human_review_status"] == "pending"


def test_validation_error_does_not_echo_untrusted_private_field(api):
    client, _, headers, *_ = api
    sentinel = "SYNTHETIC-SECRET-CANARY-DO-NOT-ECHO"
    response = client.post("/api/pilot/cases", headers=headers, json={**pilot_payload(), "operator_key": sentinel})
    assert response.status_code == 422
    assert sentinel not in response.text
    response = client.post("/api/pilot/cases", headers=headers, json={**pilot_payload(), sentinel: "arbitrary"})
    assert response.status_code == 422 and sentinel not in response.text


def test_expired_snapshot_cannot_support_current_review(api):
    client, _, headers, *_ = api
    case_id = create_run(api)
    case = client.get(f"/api/cases/{case_id}", headers=headers).json()
    receipt = client.post(f"/api/cases/{case_id}/sources", headers={**headers, "Idempotency-Key": "expired-review"}, json={
        "case_version": case["version"], "url": "https://synthetic.example.org/notice", "title": "Expired fixture",
        "captured_at": (m.utcnow()-timedelta(days=3)).isoformat(), "text": "Historical fixture only.",
        "excerpt": "Historical fixture only.", "claim": "The opportunity is current.",
        "expires_at": (m.utcnow()-timedelta(days=1)).isoformat(),
    }).json()
    prepared = client.get(f"/api/cases/{case_id}/review-inputs", headers=headers).json()["input"]
    prepared["review_note"] = "SYNTHETIC attempt to promote expired source"
    prepared["evidence_bindings"] = [{
        "evidence_id": "expired", "claim_id": receipt["claim_id"], "source_id": receipt["source_id"],
        "assertion_status": "supported", "source_permission_confirmed": True, "source_role_confirmed": True,
        "source_type": "other", "confidence_label": "low",
    }]
    response = client.post(f"/api/cases/{case_id}/review-inputs", headers={**headers, "Idempotency-Key": "review-expired"}, json=prepared)
    assert response.status_code == 422 and "Expired source" in response.text


def test_synthetic_inquiry_without_sources_stays_unknown(api):
    client, _, headers, *_ = api
    case_id = client.post("/api/pilot/cases", headers=headers, json=pilot_payload()).json()["id"]
    assert client.post(f"/api/cases/{case_id}/run", headers=headers).status_code == 200
    case = client.get(f"/api/cases/{case_id}", headers=headers).json()
    assert case["research_status"] == "PARTIAL"
    assert case["inquiry"]["buyer_email"] is None
    assert client.get(f"/api/cases/{case_id}/evidence", headers=headers).json()["claims"] == []
    assert client.get(f"/api/cases/{case_id}/risks", headers=headers).json()
    assert client.get(f"/api/cases/{case_id}/pilot-export", headers=headers).json()["business_evaluation"] is None


def test_pilot_export_rechecks_real_scope_and_retention_using_only_synthetic_bytes(api, tmp_path, monkeypatch):
    from tradecase.p7_policy import digest

    client, app, headers, *_ = api
    root = (tmp_path / "synthetic-operator-test-only").resolve()
    root.mkdir()
    payload = {**pilot_payload(), "synthetic": False, "classification": "private_cleared"}
    context = dict(run_id="TEST-ONLY", system="tradecase", tenant_id="alpha", environment="live_sandbox",
        case_id="TEST-ONLY", dataset_id=payload["dataset_id"], plan_hash="1"*64, input_hash=payload["dataset_sha256"],
        rights_hash=digest(payload["rights_reference"].encode()), provider_config_hash="2"*64,
        rights_current=True, data_classification="redacted_business", provider="stub", model="stub-model", domain="stub.invalid")
    grant = {**context, "actor_id": "SYNTHETIC-TEST-OPERATOR", "actor_origin": "operator",
        "human_reason": "SYNTHETIC regression only; not a real operator grant", "approved_at_utc": payload["captured_at"],
        "expires_at_utc": payload["retention_until"], "revoked_at_utc": None, "allow_external_writes": False,
        "export_allowed": True, "data_classifications": ["redacted_business"], "capabilities": {"inspect_customer_data": {
            "provider": "stub", "model": "stub-model", "domain": "stub.invalid", "max_requests": 1,
            "max_images": 0, "max_attempts": 1, "max_usd": 0}}}
    for name, value in [("context.json", context), ("grant.json", grant), ("isolation.json", {**context, "data_root": str(root)})]:
        path = root / name
        path.write_text(json.dumps(value))
        path.chmod(0o600)
    monkeypatch.setenv("ALLOW_TEST_LIVE", "on")
    monkeypatch.setenv("TRADECASE_P7_ROOT", str(root))
    monkeypatch.setenv("TRADECASE_P7_APPROVED_GRANT_SHA256", digest((root / "grant.json").read_bytes()))
    imported = client.post("/api/pilot/cases", headers=headers, json=payload)
    assert imported.status_code == 201, imported.text
    case_id = imported.json()["id"]
    assert client.get(f"/api/cases/{case_id}/pilot-export", headers=headers).status_code == 200
    (root / "revoked").touch()
    assert client.get(f"/api/cases/{case_id}/pilot-export", headers=headers).status_code == 403
    (root / "revoked").unlink()
    with app.state.service.db.session() as session:
        case = session.get(m.Case, case_id)
        case.data = {**case.data, "pilot": {**case.data["pilot"], "retention_until": "2000-01-01T00:00:00+00:00"}}
    assert client.get(f"/api/cases/{case_id}/pilot-export", headers=headers).status_code == 403
    legacy = client.post("/api/cases", headers=headers, json={"raw_content": "SYNTHETIC legacy unknown origin"}).json()["id"]
    assert client.get(f"/api/cases/{legacy}/pilot-export", headers=headers).status_code == 403


def test_operator_credential_rotation_revocation_and_tenant_scope(api):
    client, app, headers, other, viewer = api
    service = app.state.service
    admin = service.authenticate(headers["Authorization"][7:])
    target, old = service.provision("alpha", "SYNTHETIC rotation target", "viewer")
    with pytest.raises(ServiceError):
        service.rotate_credential(service.authenticate(other["Authorization"][7:]), target["id"])
    with pytest.raises(ServiceError):
        service.rotate_credential(service.authenticate(viewer["Authorization"][7:]), target["id"])
    replacement = service.rotate_credential(admin, target["id"])
    assert client.get("/api/me", headers={"Authorization": "Bearer " + old}).status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer " + replacement}).status_code == 200
    service.rotate_credential(admin, target["id"], revoke=True)
    assert client.get("/api/me", headers={"Authorization": "Bearer " + replacement}).status_code == 401
    with service.db.session() as session:
        audit = session.scalars(select(m.AuditLog).where(m.AuditLog.action.like("credential.%"))).all()
        assert len(audit) == 2
        assert all(old not in json.dumps(x.data_redacted) and replacement not in json.dumps(x.data_redacted) for x in audit)


def test_cli_rotation_writes_new_private_file_and_never_prints_token(api, tmp_path, monkeypatch, capsys):
    from tradecase.platform import cli

    client, app, headers, *_ = api
    target, old = app.state.service.provision("alpha", "SYNTHETIC CLI target", "viewer")
    admin_file, new_file = tmp_path / "admin", tmp_path / "replacement"
    admin_file.write_text(headers["Authorization"][7:])
    admin_file.chmod(0o600)
    monkeypatch.setattr(cli, "Settings", lambda: app.state.service.settings)
    monkeypatch.setattr("sys.argv", ["cli", "rotate-token", "--user-id", target["id"],
                                   "--token-file", str(admin_file), "--new-token-file", str(new_file)])
    cli.main()
    replacement = new_file.read_text()
    assert replacement not in capsys.readouterr().out and new_file.stat().st_mode & 0o077 == 0
    assert client.get("/api/me", headers={"Authorization": "Bearer " + old}).status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer " + replacement}).status_code == 200
    with pytest.raises(FileExistsError):
        cli.main()
    assert client.get("/api/me", headers={"Authorization": "Bearer " + replacement}).status_code == 200


def test_monitoring_counts_are_tenant_scoped_and_do_not_contain_case_text(api):
    client, _, headers, other, *_ = api
    create_run(api)
    metrics = client.get("/api/metrics", headers=headers)
    assert metrics.status_code == 200
    assert metrics.json()["task_counts"] and metrics.json()["pending_approvals"] == 1
    assert metrics.json()["outbound_counts"] == {} and metrics.json()["external_sends"] == 0
    assert client.get("/api/metrics", headers=other).json()["task_counts"] == {}
    assert "Synthetic inquiry" not in metrics.text
