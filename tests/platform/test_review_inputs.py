"""Non-synthetic schema contract tests with manually uploaded test text, no web/API calls.

Public-looking URLs here exercise validation only; quoted text is test data and
is never asserted to be an actual statement or regulation on those websites.
"""

import asyncio
import copy
from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import update

from tradecase.platform import db as m
from tradecase.platform.config import Settings
from tradecase.platform.contracts import CreateCase, Decision
from tradecase.platform.coordinator import CaseRunCoordinator
from tradecase.platform.review_inputs import ReviewInputs, ReviewInputsService
from tradecase.platform.services import CaseService, ServiceError
from tradecase.platform.source_intake import SourceInput, SourceIntakeService


@pytest.fixture
def prepared(tmp_path):
    settings = Settings(
        database_url="sqlite:///" + str(tmp_path / "db.sqlite"),
        storage_root=tmp_path / "objects",
        work_root=tmp_path / "work",
        checkpoint_url="sqlite:///" + str(tmp_path / "checkpoint.sqlite"),
    )
    settings.prepare()
    database = m.Database(settings.database_url)
    database.create_schema()
    service = CaseService(database, settings)
    _, token = service.provision("tenant-a", "Reviewer")
    actor = service.authenticate(token)
    case = service.create(
        actor,
        CreateCase(
            raw_content="Please quote 500 widgets for Amazon US.",
            buyer_company="Northstar Contract Fixture",
            buyer_email="buyer@buyer-contract.acme-corp.com",
            website="https://buyer-contract.acme-corp.com",
            buyer_country="US",
            product="widgets",
            platform="amazon_us",
        ),
        "new",
    )
    intake = SourceIntakeService(service)
    definitions = [
        (
            "buyer",
            "https://buyer-contract.acme-corp.com/about",
            "official_site",
            "Contract fixture: Northstar is a US widget distributor and this is its public company site.",
        ),
        (
            "country",
            "https://www.trade.gov/contract-fixture-rule",
            "government",
            "Contract fixture requirement: label_present must be true.",
        ),
        (
            "platform",
            "https://sellercentral.amazon.com/contract-fixture-rule",
            "platform_official",
            "Contract fixture requirement: platform_reviewed must be true.",
        ),
    ]
    bindings = []
    now = m.utcnow() - timedelta(seconds=10)
    for name, url, role, text in definitions:
        receipt = intake.submit(
            actor,
            case["id"],
            SourceInput(
                case_version=service.get(actor["tenant_id"], case["id"])["version"],
                url=url,
                title="Manual test snapshot " + name,
                captured_at=now,
                text=text,
                excerpt=text,
                claim=text,
            ),
            "source-" + name,
        )
        assert receipt["tested_live"] is False
        bindings.append(
            {
                "evidence_id": "ev-" + name,
                "claim_id": receipt["claim_id"],
                "source_id": receipt["source_id"],
                "entity_candidate_id": "buyer" if name == "buyer" else None,
                "assertion_status": "supported",
                "source_type": role,
                "source_permission_confirmed": True,
                "source_role_confirmed": True,
            }
        )
    profile = {
        "case_id": case["id"],
        "candidate_ids": ["buyer"],
        "selected_candidate_id": "buyer",
        "company_name": "Northstar Contract Fixture",
        "website": "https://buyer-contract.acme-corp.com",
        "domain": "buyer-contract.acme-corp.com",
        "country": "US",
        "buyer_role": "distributor",
        "inquiry_relationship": "Public inquiry sender",
        "claim_evidence_map": {
            key: ["ev-buyer"]
            for key in ("company_name", "website", "domain", "country", "buyer_role", "inquiry_relationship")
        },
    }
    rules = []
    for name, url, role, text in definitions[1:]:
        attribute = "label_present" if name == "country" else "platform_reviewed"
        rules.append(
            {
                "rule_id": "review-" + name,
                "check_type": name,
                "version": "contract-test-1",
                "product_scope": "widgets",
                "applicability": {"target_country": "US"} if name == "country" else {"platform": "amazon_us"},
                "attributes_required": [attribute],
                "required_values": {attribute: True},
                "source_url": url,
                "source_evidence_ids": ["ev-" + name],
                "effective_date": now.date().isoformat(),
                "reviewed_at": now.isoformat(),
                "valid_until": (now + timedelta(days=1)).isoformat(),
                "source_current": True,
                "is_synthetic": False,
                "rationale": "Contract test source-role declaration, not real law",
                "suggested_action": "Human review required",
            }
        )
    payload = {
        "case_version": service.get(actor["tenant_id"], case["id"])["version"],
        "candidates": [
            {
                "candidate_id": "buyer",
                "name": "Northstar Contract Fixture",
                "country": "US",
                "domain": "buyer-contract.acme-corp.com",
                "website": "https://buyer-contract.acme-corp.com",
                "identity_status": "supported",
                "evidence_ids": ["ev-buyer"],
            }
        ],
        "profile": profile,
        "signals": {
            key: {"value": "supported", "evidence_ids": ["ev-buyer"]}
            for key in ("verified_identity", "buyer_role_evidence", "product_fit_evidence")
        },
        "seller_context": {"product_attributes": {"label_present": True, "platform_reviewed": True}},
        "rules": {"rules": rules},
        "evidence_bindings": bindings,
        "current_rules_confirmed": True,
        "review_note": "Human contract-test review of exact uploaded snapshots; no online validation claimed.",
    }
    yield service, actor, case, payload
    database.close()


def test_reviewed_real_case_scores_and_rules_flow_through_existing_kernel(prepared):
    service, actor, case, payload = prepared
    reviewer = ReviewInputsService(service)
    request = ReviewInputs.model_validate(payload)
    receipt = reviewer.submit(actor, case["id"], request, "review")
    assert receipt["assessment"]["score"] == 70
    assert receipt["assessment"]["decision"] == "normal_priority"
    assert all(row["status"] == "pass" for row in receipt["compliance"]["checks"])
    assert reviewer.submit(actor, case["id"], request, "review") == receipt
    updated = service.get(actor["tenant_id"], case["id"])
    assert updated["version"] == payload["case_version"] + 1 and updated["workflow_run_id"] is None
    coordinator = CaseRunCoordinator(service)
    run = coordinator.request(actor, case["id"])
    result = asyncio.run(coordinator.run(actor["tenant_id"], run["id"]))
    assert result["status"] == "WAITING_HUMAN"
    updated = service.get(actor["tenant_id"], case["id"])
    assert updated["research_status"] == "COMPLETE" and not updated["synthetic"]
    assert updated["assessment"]["score"] == 70
    assert service.rows(actor["tenant_id"], case["id"], m.AgentRun) == []  # already reviewed work is reused
    approval = next(row for row in service.approvals(actor["tenant_id"]) if row["status"] == "PENDING")
    service.decide(
        actor,
        approval["id"],
        Decision(decision="approve", artifact_hash=approval["artifact_hash"], case_version=approval["case_version"]),
        "draft-review",
    )
    assert asyncio.run(CaseRunCoordinator(service).run(actor["tenant_id"], run["id"]))["status"] == "COMPLETED"
    assert service.get(actor["tenant_id"], case["id"])["status"] == "READY_TO_FOLLOW_UP"
    assert len(service.followups(actor["tenant_id"])) == 1
    bundle = reviewer.bundle(actor["tenant_id"], case["id"])
    assert all(not row["tested_live"] for row in bundle["source_declarations"])
    assert all(row["retrieval_method"] == "human_uploaded_snapshot" for row in bundle["source_declarations"])
    assert bundle["reviewer_id"] == actor["id"]


def test_review_template_requires_explicit_confirmations_and_preserves_aliases(prepared):
    service, actor, case, payload = prepared
    reviewer = ReviewInputsService(service)
    template = reviewer.template(actor["tenant_id"], case["id"])
    assert len(template["input"]["evidence_bindings"]) == 3
    assert all(not row["source_role_confirmed"] for row in template["input"]["evidence_bindings"])
    reviewer.submit(actor, case["id"], ReviewInputs.model_validate(payload), "review")
    template = reviewer.template(actor["tenant_id"], case["id"])
    assert (
        template["input"]["candidates"] == payload["candidates"]
        or template["input"]["candidates"][0]["candidate_id"] == "buyer"
    )
    assert not template["input"]["current_rules_confirmed"]
    assert all(not row["source_permission_confirmed"] for row in template["input"]["evidence_bindings"])


@pytest.mark.parametrize(
    "kind", ["stale", "bad_link", "quote", "internal_role", "current_rules", "profile_case", "bad_alias"]
)
def test_review_rejects_invalid_proposals_atomically(prepared, kind):
    service, actor, case, payload = prepared
    proposal = copy.deepcopy(payload)
    if kind == "stale":
        proposal["case_version"] -= 1
    elif kind == "bad_link":
        proposal["evidence_bindings"][0]["source_id"] = proposal["evidence_bindings"][1]["source_id"]
    elif kind == "quote":
        with service.db.session() as session:
            session.execute(
                update(m.ClaimEvidenceLink)
                .where(m.ClaimEvidenceLink.claim_id == proposal["evidence_bindings"][0]["claim_id"])
                .values(excerpt="This text was not captured")
            )
    elif kind == "internal_role":
        with service.db.session() as session:
            source = session.get(m.Source, proposal["evidence_bindings"][1]["source_id"])
            source.data = {**source.data, "authority": "user_provided_unverified"}
    elif kind == "current_rules":
        proposal["current_rules_confirmed"] = False
    elif kind == "profile_case":
        proposal["profile"]["case_id"] = "different-case"
    else:
        proposal["signals"]["verified_identity"]["evidence_ids"] = ["invented"]
    with pytest.raises(ServiceError):
        ReviewInputsService(service).submit(actor, case["id"], ReviewInputs.model_validate(proposal), "bad")
    assert service.get(actor["tenant_id"], case["id"])["version"] == payload["case_version"]
    assert not [row for row in service.artifacts(actor["tenant_id"], case["id"]) if row["kind"] == "review_inputs"]


def test_review_tenant_role_and_immutable_source_boundaries(prepared):
    service, actor, case, payload = prepared
    reviewer = ReviewInputsService(service)
    _, token = service.provision("other", "Other reviewer")
    other = service.authenticate(token)
    with pytest.raises(ServiceError) as error:
        reviewer.submit(other, case["id"], ReviewInputs.model_validate(payload), "cross-tenant")
    assert error.value.status == 404
    _, token = service.provision(actor["tenant_id"], "Operator", "operator")
    with pytest.raises(ServiceError) as error:
        reviewer.submit(service.authenticate(token), case["id"], ReviewInputs.model_validate(payload), "operator")
    assert error.value.status == 403
    changed = copy.deepcopy(payload)
    changed["evidence_bindings"][0]["source_url"] = "https://invented.com/"
    with pytest.raises(ValidationError):
        ReviewInputs.model_validate(changed)
    changed = copy.deepcopy(payload)
    changed["evidence_bindings"][0]["source_permission_confirmed"] = False
    with pytest.raises(ValidationError):
        ReviewInputs.model_validate(changed)


def test_review_invalidates_prior_approval_and_preserves_history(prepared):
    service, actor, case, payload = prepared
    coordinator = CaseRunCoordinator(service)
    run = coordinator.request(actor, case["id"])
    asyncio.run(coordinator.run(actor["tenant_id"], run["id"]))
    previous = service.approvals(actor["tenant_id"])[0]
    receipt = ReviewInputsService(service).submit(actor, case["id"], ReviewInputs.model_validate(payload), "review")
    assert receipt["artifact_id"]
    with service.db.session() as session:
        assert session.get(m.WorkflowRun, run["id"]).status == "CANCELLED"
        assert session.get(m.Approval, previous["id"]).status == "INVALIDATED"
    assert service.get(actor["tenant_id"], case["id"])["workflow_run_id"] is None
    next_run = CaseRunCoordinator(service).request(actor, case["id"])
    asyncio.run(CaseRunCoordinator(service).run(actor["tenant_id"], next_run["id"]))
    assert next_run["id"] != run["id"]
    assert len(service.approvals(actor["tenant_id"])) == 2
    risks = service.rows(actor["tenant_id"], case["id"], m.RiskFinding)
    active = [row for row in risks if row["data"].get("active", True)]
    assert len(active) == 2 and all(row["status"] == "pass" for row in active)
    assert len(risks) == 4 and all(row["data"]["active"] is False for row in risks if row not in active)
