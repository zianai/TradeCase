"""Versioned, reproducible inquiry-follow-up heuristics; never a credit rating.

The host Agent supplies discrete, sourced signals. This module validates their
structural suitability and applies fixed rules without an Agent execution loop.
It cannot independently prove the meaning or truth of natural-language claims.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from tradecase_upstream.extract_contacts import FREE_MAIL_DOMAINS, normalized_domain

from tradecase.models import Assessment, BuyerProfile, Candidate, CaseInput, Evidence, Signal

if TYPE_CHECKING:
    from tradecase.case_store import CaseStore

RULE_VERSION = "priority-v1"
WEIGHTS = {
    "verified_identity": 20,
    "buyer_role_evidence": 25,
    "product_fit_evidence": 25,
    "inquiry_specificity": 20,
    "contactability": 10,
}
MINIMUM_COVERAGE = 0.6
HIGH_PRIORITY_SCORE = 80
NORMAL_PRIORITY_SCORE = 50
FINAL_SOURCE_TYPES = {"official_site", "government", "platform_official", "registry", "news"}


def _unique_index(rows, key):
    result = {}
    for row in rows:
        identity = getattr(row, key)
        if identity in result:
            raise ValueError(f"duplicate {key}: {identity}")
        result[identity] = row
    return result


def _references(ids, evidence, label):
    missing = sorted(set(ids) - evidence.keys())
    if missing:
        raise ValueError(f"{label}: unknown evidence IDs: {', '.join(missing)}")
    return [evidence[eid] for eid in ids]


def _is_final(row):
    return row.source_type in FINAL_SOURCE_TYPES and row.source_url is not None


def _validate_signal(name, signal, inquiry, profile, candidates, evidence):
    linked = _references(signal.evidence_ids, evidence, name)
    if signal.value == "unknown":
        return
    if name != "inquiry_specificity" and not profile.selected_candidate_id:
        raise ValueError(f"{name}: known signal requires a selected entity")
    expected_status = "supported" if signal.value == "supported" else "contradicted"
    for row in linked:
        if row.assertion_status != expected_status:
            raise ValueError(f"{name}: evidence assertion_status must be {expected_status}")
        if name == "inquiry_specificity" and row.source_type == "user_provided":
            if row.local_snapshot_ref != "input.json" or not row.excerpt or row.excerpt not in inquiry.buyer_message:
                raise ValueError("inquiry_specificity: user-provided evidence must quote the actual inquiry input.json")
        elif not _is_final(row):
            raise ValueError(f"{name}: source {row.source_type} is not final evidence; snippets cannot score")
        if row.entity_candidate_id and row.entity_candidate_id != profile.selected_candidate_id:
            raise ValueError(f"{name}: evidence refers to a different entity")
        if name != "inquiry_specificity" and row.entity_candidate_id != profile.selected_candidate_id:
            raise ValueError(f"{name}: evidence must be explicitly bound to the selected entity")
    if signal.value == "supported" and name in {"verified_identity", "buyer_role_evidence"}:
        selected = candidates.get(profile.selected_candidate_id)
        if not selected or selected.identity_status != "supported":
            raise ValueError(f"{name}: supported signal requires a supported selected entity")
    if signal.value == "supported" and name == "contactability":
        valid_contacts = [
            contact for contact in profile.contacts
            if contact.source_class == "public" and contact.source_url and any(
                row.evidence_id in contact.evidence_ids and row.source_url == contact.source_url
                and row.excerpt and contact.email.casefold() in row.excerpt.casefold() for row in linked
            )
        ]
        if not valid_contacts:
            raise ValueError("contactability: requires a public contact quoted in matching source evidence")


def _related_domains(left, right):
    return left == right or left.endswith("." + right) or right.endswith("." + left)


def _entity_conflicts(inquiry, buyer, selected):
    if not selected:
        return []
    reasons = []
    selected_domains = [normalized_domain(value) for value in (selected.website, selected.domain) if value]
    profile_domains = [normalized_domain(value) for value in (buyer.website, buyer.domain) if value]
    domains = [value for value in selected_domains + profile_domains if value]
    country_conflict = (
        selected.country and buyer.country and selected.country.casefold() not in {"unknown", "unverified"}
        and buyer.country.casefold() not in {"unknown", "unverified"}
        and selected.country.casefold() != buyer.country.casefold()
    )
    if country_conflict or any(not _related_domains(left, right) for left in domains for right in domains):
        reasons.append("ENTITY_FIELD_CONFLICT")
    incoming = []
    if inquiry.buyer_email:
        domain = inquiry.buyer_email.rsplit("@", 1)[1].casefold()
        if domain not in FREE_MAIL_DOMAINS:
            incoming.append(domain)
    if inquiry.buyer_website_hint:
        incoming.append(normalized_domain(inquiry.buyer_website_hint))
    if selected_domains and any(
        not any(_related_domains(value, selected_domain) for selected_domain in selected_domains) for value in incoming
    ):
        reasons.append("INQUIRY_DOMAIN_CONFLICT")
    return reasons


def calculate_assessment(
    case_input: dict,
    profile: dict,
    candidates: list[dict],
    evidence: list[dict],
    signals: dict,
) -> dict:
    """Validate Agent signals and return deterministic schema-v1 output.

    Coverage is the sum of weights of evidenced known signals / 100. A negative
    signal is known and contributes coverage but zero priority points. Publicly
    listed email contactability does not imply mailbox ownership verification.
    """
    inquiry = CaseInput.model_validate(case_input)
    buyer = BuyerProfile.model_validate(profile)
    if buyer.case_id != inquiry.case_id:
        raise ValueError("buyer_profile case_id does not match input")
    if not isinstance(signals, dict) or set(signals) - WEIGHTS.keys():
        raise ValueError("unknown assessment signal name")
    candidate_rows = [Candidate.model_validate(row) for row in candidates]
    evidence_rows = [Evidence.model_validate(row) for row in evidence]
    candidate_index = _unique_index(candidate_rows, "candidate_id")
    evidence_index = _unique_index(evidence_rows, "evidence_id")
    if set(buyer.candidate_ids) - candidate_index.keys():
        raise ValueError("buyer_profile references unknown candidate IDs")
    for row in evidence_rows:
        if row.entity_candidate_id and row.entity_candidate_id not in candidate_index:
            raise ValueError(f"evidence {row.evidence_id}: unknown entity_candidate_id")
    for candidate in candidate_rows:
        linked = _references(candidate.evidence_ids, evidence_index, f"candidate {candidate.candidate_id}")
        if candidate.identity_status == "supported" and not any(
            _is_final(row) and row.assertion_status == "supported" and row.entity_candidate_id == candidate.candidate_id
            for row in linked
        ):
            raise ValueError(f"candidate {candidate.candidate_id}: supported identity lacks final entity evidence")
    for key, ids in buyer.claim_evidence_map.items():
        _references(ids, evidence_index, f"buyer claim {key}")
    for contact in buyer.contacts:
        _references(contact.evidence_ids, evidence_index, "contact")
    if not inquiry.is_synthetic and any(row.is_synthetic for row in [buyer, *candidate_rows, *evidence_rows]):
        raise ValueError("synthetic data cannot score a real Case")
    normalized = {name: Signal.model_validate(signals.get(name, {})) for name in WEIGHTS}
    for name, signal in normalized.items():
        _validate_signal(name, signal, inquiry, buyer, candidate_index, evidence_index)

    known_weight = sum(WEIGHTS[name] for name, signal in normalized.items() if signal.value != "unknown")
    score = sum(WEIGHTS[name] for name, signal in normalized.items() if signal.value == "supported")
    coverage = known_weight / 100
    reasons = []
    missing = [name for name, signal in normalized.items() if signal.value == "unknown"]
    selected = candidate_index.get(buyer.selected_candidate_id)
    reasons.extend(_entity_conflicts(inquiry, buyer, selected))
    if coverage < MINIMUM_COVERAGE:
        reasons.append("INSUFFICIENT_EVIDENCE_COVERAGE")
        score = None
    if normalized["verified_identity"].value != "supported":
        reasons.append("IDENTITY_NOT_SUPPORTED")
    if normalized["buyer_role_evidence"].value != "supported":
        reasons.append("BUYER_ROLE_NOT_SUPPORTED")
    if not selected:
        reasons.append("ENTITY_NOT_SELECTED")
    elif selected.identity_status != "supported":
        reasons.append("ENTITY_NOT_SUPPORTED")
    if any(candidate_index[cid].identity_status == "ambiguous" for cid in buyer.candidate_ids):
        reasons.append("ENTITY_AMBIGUOUS")
    if buyer.unresolved_items:
        reasons.append("BUYER_UNRESOLVED")
        missing.extend(buyer.unresolved_items)
    reasons.extend(f"CONTRADICTED_{name.upper()}" for name, signal in normalized.items() if signal.value == "contradicted")
    if reasons:
        decision = "needs_review"
    elif score >= HIGH_PRIORITY_SCORE:
        decision = "high_priority"
    elif score >= NORMAL_PRIORITY_SCORE:
        decision = "normal_priority"
    else:
        decision = "low_priority"
    return Assessment(
        case_id=inquiry.case_id,
        rule_version=RULE_VERSION,
        signals=normalized,
        evidence_coverage=coverage,
        score=score,
        decision=decision,
        reason_codes=sorted(set(reasons)),
        missing_information=sorted(set(missing)),
        is_synthetic=inquiry.is_synthetic,
    ).model_dump(mode="json")


def assess_case(store: CaseStore) -> dict:
    """Read persistent Agent signals, recalculate and save the assessment."""
    inquiry = store.read("input.json")

    def optional(name, default):
        try:
            return store.read(name)
        except FileNotFoundError:
            return default

    profile = optional("buyer_profile.json", {"case_id": inquiry["case_id"], "is_synthetic": inquiry["is_synthetic"]})
    result = calculate_assessment(
        inquiry,
        profile,
        optional("candidates.jsonl", []),
        optional("evidence.jsonl", []),
        optional("assessment.json", {}).get("signals", {}),
    )
    state = store.read("manifest.json")["state"]
    if state in {"completed", "cancelled"}:
        raise ValueError("final Case requires explicit reopen before assessment")
    store.transition("running", "assessment")
    store.write("assessment.json", result)
    if result["decision"] == "needs_review":
        store.transition("needs_review", "assessment", blockers=result["reason_codes"])
    return result
