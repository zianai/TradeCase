"""Negative and boundary tests for the versioned Case contracts."""

import hashlib
import json

import pytest
from pydantic import ValidationError

from tradecase.models import CaseInput, ComplianceCheck, Contact, Evidence, Manifest
from tradecase.validation import validate_artifact, validate_case

STAMP = "2026-10-27T16:00:00Z"


def inquiry(**overrides):
    return dict(schema_version="1.0", case_id="case-test", received_at=STAMP,
                buyer_message="Please provide product details.", **overrides)


def evidence(**overrides):
    result = dict(evidence_id="ev-1", claim="Company sells widgets", source_url="https://widgets.example/about",
                  source_type="official_site", captured_at=STAMP, retrieved_by="fixture",
                  excerpt="We sell widgets.", assertion_status="supported", is_synthetic=True,
                  entity_candidate_id="company-1")
    result.update(overrides)
    return result


def check(**overrides):
    result = dict(check_id="check-1", check_type="country", jurisdiction="US", product_scope="widget",
                  rule_id="fixture-rule", rule_version="1", checked_at=STAMP,
                  source_url="https://regulator.example/rule", required_attributes=["material"],
                  observed_attributes=["material"], status="pass", severity="info", rationale="Fixture only",
                  suggested_action="Review manually", evidence_ids=["ev-1"], is_synthetic=True)
    result.update(overrides)
    return result


def partial_case(tmp_path):
    def put(name, obj):
        path = tmp_path / name
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
        return hashlib.sha256(path.read_bytes()).hexdigest()
    input_hash = put("input.json", inquiry(is_synthetic=True))
    seller_hash = put("seller_context.json", {"is_synthetic": True})
    event = dict(case_id="case-test", event_id="event-0", timestamp=STAMP, event_type="created", stage="init",
                 revision=0, detail={})
    (tmp_path / "events.jsonl").write_text(json.dumps(event) + "\n")
    put("manifest.json", dict(case_id="case-test", created_at=STAMP, updated_at=STAMP, input_hash=input_hash,
                             artifact_index={"input.json": input_hash, "seller_context.json": seller_hash}))
    return put


def test_input_accepts_unknown_nullable_fields():
    model = CaseInput.model_validate(inquiry())
    assert model.target_country is None
    assert model.product_summary is None
    assert model.schema_version == "1.0"


@pytest.mark.parametrize("change", [{"case_id": "../escape"}, {"received_at": "2026-10-27T12:00:00-04:00"},
                                    {"received_at": "2026-10-27T16:00:00"}, {"schema_version": "2.0"},
                                    {"invented": True}, {"is_synthetic": "false"}])
def test_input_rejects_bad_contract(change):
    payload = inquiry()
    payload.update(change)
    with pytest.raises(ValidationError):
        CaseInput.model_validate(payload)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)", "https://user:password@host.example",
                                  "https://", "https://host.example/\nheader"])
def test_evidence_rejects_unsafe_url(url):
    with pytest.raises(ValidationError):
        Evidence.model_validate(evidence(source_url=url))


def test_supported_evidence_requires_quotation_or_locator():
    with pytest.raises(ValidationError):
        Evidence.model_validate(evidence(excerpt=None))


def test_synthetic_flag_must_be_explicit_on_evidence():
    payload = evidence()
    del payload["is_synthetic"]
    with pytest.raises(ValidationError):
        Evidence.model_validate(payload)


def test_inferred_contact_cannot_be_verified_or_sendable():
    with pytest.raises(ValidationError):
        Contact(email="purchasing@company.example", source_class="inferred", verified=True)
    with pytest.raises(ValidationError):
        Contact(email="purchasing@company.example", send_allowed=True)


@pytest.mark.parametrize("change", [{"source_url": None}, {"rule_version": None}, {"evidence_ids": []},
                                    {"missing_items": ["material"]}, {"observed_attributes": []}])
def test_pass_requires_source_version_attributes_and_evidence(change):
    with pytest.raises(ValidationError):
        ComplianceCheck.model_validate(check(**change))


def test_manifest_rejects_hash_and_path_ambiguity():
    with pytest.raises(ValidationError):
        Manifest(case_id="x", created_at=STAMP, updated_at=STAMP, input_hash="not-a-hash")
    with pytest.raises(ValidationError):
        Manifest(case_id="x", created_at=STAMP, updated_at=STAMP, input_hash="0" * 64,
                 artifact_index={"../secret": "0" * 64})


def test_known_jsonl_artifact_validates_all_rows():
    rows = validate_artifact("evidence.jsonl", [evidence()])
    assert rows[0].evidence_id == "ev-1"
    with pytest.raises(ValueError):
        validate_artifact("unknown.json", {})


def test_partial_case_valid_but_strict_requires_deliverables(tmp_path):
    partial_case(tmp_path)
    assert validate_case(tmp_path) == []
    errors = validate_case(tmp_path, strict=True)
    assert any("buyer_profile.json" in error for error in errors)
    assert any("report.md" in error for error in errors)


def test_mutated_artifact_is_detected(tmp_path):
    partial_case(tmp_path)
    (tmp_path / "input.json").write_text(json.dumps(inquiry(is_synthetic=True, product_summary="modified")))
    errors = validate_case(tmp_path)
    assert any("input_hash" in error for error in errors)
    assert any("hash" in error and "input.json" in error for error in errors)


def test_dangling_evidence_and_entity_references(tmp_path):
    put = partial_case(tmp_path)
    put("buyer_profile.json", dict(case_id="case-test", candidate_ids=["absent-company"],
                                   company_name="Acme", claim_evidence_map={"company_name": ["absent-evidence"]},
                                   is_synthetic=True))
    errors = validate_case(tmp_path)
    assert any("absent-company" in error for error in errors)
    assert any("absent-evidence" in error for error in errors)


def test_jsonl_partial_tail_is_error_without_mutation(tmp_path):
    partial_case(tmp_path)
    path = tmp_path / "evidence.jsonl"
    path.write_text(json.dumps(evidence()) + '\n{"evidence_id":')
    before = path.read_bytes()
    errors = validate_case(tmp_path)
    assert any("evidence.jsonl" in error for error in errors)
    assert path.read_bytes() == before


def test_event_order_and_manifest_revision_must_agree(tmp_path):
    put = partial_case(tmp_path)
    path = tmp_path / "events.jsonl"
    event = json.loads(path.read_text())
    event.update(event_id="event-next", revision=2)
    with path.open("a") as stream:
        stream.write(json.dumps(event) + "\n")
    assert any("revision" in error for error in validate_case(tmp_path))
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["revision"] = 2
    put("manifest.json", manifest)
    assert validate_case(tmp_path) == []


def test_symlink_evidence_snapshot_not_followed(tmp_path):
    partial_case(tmp_path)
    (tmp_path / "snapshot.txt").symlink_to("/etc/passwd")
    row = evidence(local_snapshot_ref="snapshot.txt", entity_candidate_id=None)
    (tmp_path / "evidence.jsonl").write_text(json.dumps(row) + "\n")
    assert any("snapshot" in error for error in validate_case(tmp_path))


def test_live_case_cannot_silently_use_synthetic_evidence(tmp_path):
    put = partial_case(tmp_path)
    digest = put("input.json", inquiry())
    put("seller_context.json", {})
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest.update(input_hash=digest, artifact_index={"input.json": digest})
    put("manifest.json", manifest)
    row = evidence(entity_candidate_id=None)
    (tmp_path / "evidence.jsonl").write_text(json.dumps(row) + "\n")
    assert any("synthetic" in error for error in validate_case(tmp_path))


def test_duplicate_evidence_ids_are_rejected(tmp_path):
    partial_case(tmp_path)
    row = evidence(entity_candidate_id=None)
    (tmp_path / "evidence.jsonl").write_text((json.dumps(row) + "\n") * 2)
    assert any("duplicate evidence_id" in error for error in validate_case(tmp_path))


def test_verified_identity_cannot_use_other_entity_or_search_snippet(tmp_path):
    put = partial_case(tmp_path)
    candidate = dict(candidate_id="company-1", name="Acme", identity_status="unverified", is_synthetic=True)
    (tmp_path / "candidates.jsonl").write_text(json.dumps(candidate) + "\n")
    row = evidence(source_type="search_snippet")
    (tmp_path / "evidence.jsonl").write_text(json.dumps(row) + "\n")
    put("buyer_profile.json", dict(case_id="case-test", candidate_ids=["company-1"],
                                   selected_candidate_id="company-1", is_synthetic=True))
    put("assessment.json", dict(case_id="case-test", is_synthetic=True,
                                signals={"verified_identity": {"value": "supported", "evidence_ids": ["ev-1"]}}))
    assert any("entity-bound final evidence" in error for error in validate_case(tmp_path))


def test_compliance_pass_cannot_use_company_site_as_law(tmp_path):
    put = partial_case(tmp_path)
    digest = put("input.json", inquiry(is_synthetic=True, target_country="US"))
    put("seller_context.json", dict(is_synthetic=True, product_attributes={"material": "steel"}))
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest.update(input_hash=digest, artifact_index={"input.json": digest})
    put("manifest.json", manifest)
    row = evidence(entity_candidate_id=None, source_url="https://regulator.example/rule")
    (tmp_path / "evidence.jsonl").write_text(json.dumps(row) + "\n")
    put("compliance.json", dict(case_id="case-test", is_synthetic=True, checks=[check()]))
    assert any("official rule evidence" in error for error in validate_case(tmp_path))


def test_completed_manifest_cannot_hide_missing_deliverables(tmp_path):
    put = partial_case(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["state"] = "completed"
    put("manifest.json", manifest)
    assert any("report.md" in error for error in validate_case(tmp_path))


def test_unverified_fact_is_not_promoted_by_reference_alone(tmp_path):
    put = partial_case(tmp_path)
    row = evidence(entity_candidate_id=None, source_type="search_snippet", assertion_status="unverified")
    (tmp_path / "evidence.jsonl").write_text(json.dumps(row) + "\n")
    put("buyer_profile.json", dict(case_id="case-test", company_name="Acme", is_synthetic=True,
                                   claim_evidence_map={"company_name": ["ev-1"]}))
    assert any("unverified" in error and "company_name" in error for error in validate_case(tmp_path))


def test_original_bytes_preserved_and_hash_checked():
    import base64
    raw = b'Subject: bad encoding\n\n\xff\xfe'
    payload = inquiry(raw_bytes_base64=base64.b64encode(raw).decode("ascii"), raw_sha256=hashlib.sha256(raw).hexdigest())
    model = CaseInput.model_validate(payload)
    assert base64.b64decode(model.raw_bytes_base64) == raw
    payload["raw_sha256"] = "0" * 64
    with pytest.raises(ValidationError):
        CaseInput.model_validate(payload)
    payload["raw_bytes_base64"] = "NOT_VALID_BASE64!"
    with pytest.raises(ValidationError):
        CaseInput.model_validate(payload)


def complete_case(tmp_path):
    from tradecase.assessment import calculate_assessment

    put = partial_case(tmp_path)
    (tmp_path / "candidates.jsonl").write_text("")
    (tmp_path / "evidence.jsonl").write_text("")
    put("buyer_profile.json", dict(case_id="case-test", is_synthetic=True))
    put("assessment.json", calculate_assessment(
        inquiry(is_synthetic=True), dict(case_id="case-test", is_synthetic=True), [], [], {},
    ))
    checks = [
        check(check_id="check-country", status="needs_context", evidence_ids=[], source_url=None),
        check(check_id="check-platform", check_type="platform", platform=None, status="needs_context",
              evidence_ids=[], source_url=None),
    ]
    put("compliance.json", dict(case_id="case-test", is_synthetic=True, checks=checks))
    put("next_actions.json", dict(case_id="case-test", is_synthetic=True))
    for name in ("search_plan.md", "reply_draft.md", "report.md"):
        (tmp_path / name).write_text("Synthetic offline fixture, review required.\n")
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["state"] = "needs_review"
    manifest["artifact_index"] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in tmp_path.iterdir() if path.name not in {"manifest.json", "events.jsonl"}
    }
    put("manifest.json", manifest)
    return put


def test_pending_transaction_is_reported_without_recovery(tmp_path):
    partial_case(tmp_path)
    (tmp_path / ".transaction.json").write_text('{"pending":true}')
    assert any("transaction" in error for error in validate_case(tmp_path))
    assert (tmp_path / ".transaction.json").read_text() == '{"pending":true}'


def test_strict_requires_all_artifacts_to_be_indexed(tmp_path):
    put = complete_case(tmp_path)
    assert validate_case(tmp_path, strict=True) == []
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    del manifest["artifact_index"]["report.md"]
    put("manifest.json", manifest)
    assert validate_case(tmp_path) == []
    assert any("report.md" in error and "index" in error for error in validate_case(tmp_path, strict=True))


def test_completed_cannot_override_pending_business_review(tmp_path):
    put = complete_case(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["state"] = "completed"
    put("manifest.json", manifest)
    errors = validate_case(tmp_path)
    assert any("completed" in error and "assessment" in error for error in errors)
    assert any("completed" in error and "compliance" in error for error in errors)


def test_symlink_ancestor_of_case_is_rejected(tmp_path):
    actual = tmp_path / "actual" / "case"
    actual.mkdir(parents=True)
    partial_case(actual)
    (tmp_path / "link").symlink_to(tmp_path / "actual", target_is_directory=True)
    assert any("symlink" in error for error in validate_case(tmp_path / "link" / "case"))
