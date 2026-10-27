"""Read-only cross-artifact validation for persistent TradeCase files."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from tradecase.models import (
    Assessment,
    BuyerProfile,
    Candidate,
    CaseInput,
    ComplianceResult,
    DraftReview,
    Evidence,
    Manifest,
    NextActions,
    RuleSet,
    SellerContext,
    TaskEvent,
    relative_reference,
)

JSON_MODELS = {
    "input.json": CaseInput,
    "seller_context.json": SellerContext,
    "buyer_profile.json": BuyerProfile,
    "assessment.json": Assessment,
    "compliance.json": ComplianceResult,
    "rules_snapshot.json": RuleSet,
    "draft_review.json": DraftReview,
    "next_actions.json": NextActions,
    "manifest.json": Manifest,
}
JSONL_MODELS = {"candidates.jsonl": Candidate, "evidence.jsonl": Evidence, "events.jsonl": TaskEvent}
TEXT_ARTIFACTS = {"search_plan.md", "reply_draft.md", "report.md"}
KNOWN_ARTIFACTS = frozenset(JSON_MODELS) | frozenset(JSONL_MODELS) | TEXT_ARTIFACTS
REQUIRED_ARTIFACTS = KNOWN_ARTIFACTS - {"rules_snapshot.json"}
MINIMUM_ARTIFACTS = {"input.json", "seller_context.json", "manifest.json", "events.jsonl"}


def validate_artifact(name: str, data: Any) -> BaseModel | list[BaseModel] | str:
    """Validate one known artifact; never transform unknown files into valid output."""
    if name in JSON_MODELS:
        return JSON_MODELS[name].model_validate(data)
    if name in JSONL_MODELS:
        if not isinstance(data, list):
            raise ValueError(f"{name}: expected a list of JSONL records")
        return [JSONL_MODELS[name].model_validate(row) for row in data]
    if name in TEXT_ARTIFACTS:
        if not isinstance(data, str) or not data.strip():
            raise ValueError(f"{name}: expected non-empty text")
        return data
    raise ValueError(f"unknown artifact: {name}")


def safe_case_file(root: Path, reference: str) -> Path:
    """Refuse traversal and symlinks before reading a Case-local artifact."""
    relative_reference(reference)
    current = root
    for component in Path(reference).parts:
        current = current / component
        if current.is_symlink():
            raise ValueError(f"unsafe symlink reference: {reference}")
    if not current.is_file():
        raise ValueError(f"missing regular file: {reference}")
    return current


def _load(root: Path, name: str):
    path = safe_case_file(root, name)
    text = path.read_text(encoding="utf-8")
    if name in JSON_MODELS:
        value = json.loads(text)
    elif name in JSONL_MODELS:
        if text and not text.endswith("\n"):
            raise ValueError("JSONL must end with a complete newline-terminated record")
        value = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        value = text
    return validate_artifact(name, value)


def _references(ids: list[str], evidence: dict[str, Evidence], context: str, errors: list[str]):
    for evidence_id in ids:
        if evidence_id not in evidence:
            errors.append(f"{context}: unknown evidence_id {evidence_id}")
    return [evidence[evidence_id] for evidence_id in ids if evidence_id in evidence]


def _duplicate_ids(rows, attribute: str, context: str, errors: list[str]):
    seen = set()
    for row in rows:
        value = getattr(row, attribute)
        if value in seen:
            errors.append(f"{context}: duplicate {attribute} {value}")
        seen.add(value)


def _final_evidence(row: Evidence) -> bool:
    return row.assertion_status == "supported" and row.source_type not in {
        "search_snippet", "directory", "user_provided", "other",
    }


def validate_case(path: str | Path, strict: bool = False) -> list[str]:
    """Return contextual errors, leaving partial/torn files untouched for recovery.

    `strict` validates a completed set of deliverables, not a positive business
    outcome: complete, honestly marked needs_review Cases can pass validation.
    """
    root = Path(path).absolute()
    if any(part.is_symlink() for part in (root, *root.parents)):
        return ["case: symlink in Case path or ancestor is not permitted"]
    if not root.is_dir():
        return ["case: expected a regular directory, not a symlink"]
    errors: list[str] = []
    if (root / ".transaction.json").exists() or (root / ".transaction.json").is_symlink():
        errors.append("case: pending .transaction.json; recover before validating completed state")
    artifacts: dict[str, Any] = {}
    for name in sorted(KNOWN_ARTIFACTS):
        if not (root / name).exists() and not (root / name).is_symlink():
            continue
        try:
            artifacts[name] = _load(root, name)
        except (ValueError, OSError, ValidationError) as exc:
            errors.append(f"{name}: {exc}")
    manifest: Manifest | None = artifacts.get("manifest.json")
    complete_set = strict or bool(manifest and manifest.state == "completed")
    required = REQUIRED_ARTIFACTS if complete_set else MINIMUM_ARTIFACTS
    for name in sorted(required):
        if not (root / name).exists():
            errors.append(f"missing required artifact: {name}")

    inquiry: CaseInput | None = artifacts.get("input.json")
    if manifest:
        if complete_set:
            for name in sorted(artifacts.keys() - {"manifest.json", "events.jsonl"}):
                if name not in manifest.artifact_index:
                    errors.append(f"manifest.json: artifact_index missing {name}")
        for name, digest in manifest.artifact_index.items():
            try:
                actual = hashlib.sha256(safe_case_file(root, name).read_bytes()).hexdigest()
                if actual != digest:
                    errors.append(f"manifest.json: artifact hash mismatch for {name}")
            except ValueError as exc:
                errors.append(f"manifest.json: {exc}")
        if "input.json" in artifacts:
            digest = hashlib.sha256((root / "input.json").read_bytes()).hexdigest()
            if digest != manifest.input_hash:
                errors.append("manifest.json: input_hash mismatch")
        for name, value in artifacts.items():
            values = value if isinstance(value, list) else [value]
            for row in values:
                if hasattr(row, "case_id") and row.case_id != manifest.case_id:
                    errors.append(f"{name}: case_id does not match manifest")

    events: list[TaskEvent] = artifacts.get("events.jsonl", [])
    _duplicate_ids(events, "event_id", "events.jsonl", errors)
    previous_revision = -1
    previous_timestamp = None
    for event in events:
        if event.revision <= previous_revision:
            errors.append("events.jsonl: revision must increase strictly")
        timestamp = datetime.fromisoformat(event.timestamp)
        if previous_timestamp and timestamp < previous_timestamp:
            errors.append("events.jsonl: timestamps must not move backwards")
        previous_revision, previous_timestamp = event.revision, timestamp
    if manifest and events and events[-1].revision != manifest.revision:
        errors.append("events.jsonl: last revision does not match manifest.revision")
    if manifest and "events.jsonl" in artifacts and not events:
        errors.append("events.jsonl: Case must have an initial event")

    candidates: list[Candidate] = artifacts.get("candidates.jsonl", [])
    _duplicate_ids(candidates, "candidate_id", "candidates.jsonl", errors)
    candidate_map = {row.candidate_id: row for row in candidates}
    rows: list[Evidence] = artifacts.get("evidence.jsonl", [])
    _duplicate_ids(rows, "evidence_id", "evidence.jsonl", errors)
    evidence = {row.evidence_id: row for row in rows}
    for row in rows:
        if row.entity_candidate_id and row.entity_candidate_id not in candidate_map:
            errors.append(f"evidence.jsonl: unknown entity_candidate_id {row.entity_candidate_id}")
        if row.local_snapshot_ref:
            try:
                safe_case_file(root, row.local_snapshot_ref)
                if not manifest or row.local_snapshot_ref not in manifest.artifact_index:
                    errors.append(f"evidence.jsonl {row.evidence_id}: snapshot must be indexed with a content hash")
            except ValueError as exc:
                errors.append(f"evidence.jsonl {row.evidence_id}: {exc}")
    for candidate in candidates:
        linked = _references(candidate.evidence_ids, evidence, f"candidate {candidate.candidate_id}", errors)
        if candidate.identity_status == "supported" and not any(
            _final_evidence(row) and row.entity_candidate_id == candidate.candidate_id for row in linked
        ):
            errors.append(f"candidate {candidate.candidate_id}: supported identity lacks entity-bound final evidence")

    profile: BuyerProfile | None = artifacts.get("buyer_profile.json")
    if profile:
        for candidate_id in profile.candidate_ids:
            if candidate_id not in candidate_map:
                errors.append(f"buyer_profile.json: unknown candidate_id {candidate_id}")
        for claim, ids in profile.claim_evidence_map.items():
            linked = _references(ids, evidence, f"buyer_profile.json claim {claim}", errors)
            for row in linked:
                if row.entity_candidate_id and row.entity_candidate_id != profile.selected_candidate_id:
                    errors.append(f"buyer_profile.json claim {claim}: evidence belongs to another entity")
        for key in ("company_name", "website", "domain", "country", "buyer_role", "inquiry_relationship"):
            value = getattr(profile, key)
            unresolved = any(key in item for item in profile.unresolved_items)
            ids = profile.claim_evidence_map.get(key, [])
            if value and not ids and not unresolved:
                errors.append(f"buyer_profile.json: {key} requires evidence or explicit unresolved_items annotation")
            if value and ids and not unresolved and not any(
                _final_evidence(evidence[evidence_id]) for evidence_id in ids if evidence_id in evidence
            ):
                errors.append(f"buyer_profile.json: {key} remains unverified; annotate unresolved_items")
        for contact in profile.contacts:
            linked = _references(contact.evidence_ids, evidence, "buyer_profile.json contact", errors)
            if contact.verified and not any(
                _final_evidence(row) and row.source_url == contact.source_url
                and row.entity_candidate_id == profile.selected_candidate_id for row in linked
            ):
                errors.append("buyer_profile.json: verified contact lacks matching final source evidence")

    assessment: Assessment | None = artifacts.get("assessment.json")
    if assessment:
        for name, signal in assessment.signals.items():
            linked = _references(signal.evidence_ids, evidence, f"assessment.json {name}", errors)
            if signal.value == "supported" and not any(row.assertion_status == "supported" for row in linked):
                errors.append(f"assessment.json {name}: supported signal lacks supported evidence")
            if signal.value == "supported" and name in {"verified_identity", "buyer_role_evidence"}:
                selected = profile.selected_candidate_id if profile else None
                if not selected or not any(
                    _final_evidence(row) and row.entity_candidate_id == selected for row in linked
                ):
                    errors.append(f"assessment.json {name}: requires entity-bound final evidence")
                candidate = candidate_map.get(selected)
                if not candidate or candidate.identity_status != "supported":
                    errors.append(f"assessment.json {name}: selected entity is not supported")
        if inquiry:
            # Local import keeps the scorer independent from the persistence
            # validator and avoids the CaseStore -> validation -> scorer cycle.
            from tradecase.assessment import calculate_assessment

            try:
                recomputed = calculate_assessment(
                    inquiry.model_dump(mode="json"),
                    profile.model_dump(mode="json") if profile else {
                        "case_id": inquiry.case_id, "is_synthetic": inquiry.is_synthetic,
                    },
                    [candidate.model_dump(mode="json") for candidate in candidates],
                    [row.model_dump(mode="json") for row in rows],
                    {key: signal.model_dump(mode="json") for key, signal in assessment.signals.items()},
                )
                actual = assessment.model_dump(mode="json")
                for key in ("rule_version", "score", "decision", "evidence_coverage", "reason_codes", "missing_information"):
                    if actual[key] != recomputed[key]:
                        errors.append(f"assessment.json: {key} does not match recomputed priority-v1 derivation")
            except ValueError as exc:
                errors.append(f"assessment.json: invalid signal derivation: {exc}")

    compliance: ComplianceResult | None = artifacts.get("compliance.json")
    rules_snapshot: RuleSet | None = artifacts.get("rules_snapshot.json")
    seller: SellerContext | None = artifacts.get("seller_context.json")
    if compliance:
        _duplicate_ids(compliance.checks, "check_id", "compliance.json", errors)
        if complete_set and {check.check_type for check in compliance.checks} != {"country", "platform"}:
            errors.append("compliance.json: strict Case requires country and platform checks")
        for check in compliance.checks:
            linked = _references(check.evidence_ids, evidence, f"compliance.json {check.check_id}", errors)
            if check.status != "pass":
                continue
            expected_type = "government" if check.check_type == "country" else "platform_official"
            if not any(
                row.source_type == expected_type and row.source_url == check.source_url
                and row.assertion_status == "supported" for row in linked
            ):
                errors.append(f"compliance.json {check.check_id}: pass lacks matching official rule evidence")
            if inquiry:
                applicable = inquiry.target_country if check.check_type == "country" else inquiry.platform
                observed = check.jurisdiction if check.check_type == "country" else check.platform
                if not applicable or applicable != observed:
                    errors.append(f"compliance.json {check.check_id}: pass does not match Case context")
            if check.effective_date and date.fromisoformat(check.effective_date) > datetime.fromisoformat(check.checked_at).date():
                errors.append(f"compliance.json {check.check_id}: rule not yet effective at check time")
            for attribute in check.required_attributes:
                if not seller or seller.product_attributes.get(attribute) in (None, ""):
                    errors.append(f"compliance.json {check.check_id}: required seller attribute {attribute} missing")
        if rules_snapshot is None:
            errors.append("compliance.json: rules_snapshot.json is required to verify the deterministic checks")
        if not compliance.checked_at or not compliance.rules_snapshot_sha256 or not compliance.rules_snapshot_ref:
            errors.append("compliance.json: checked_at and rules snapshot hash binding are required")
        if rules_snapshot and compliance.rules_snapshot_sha256:
            snapshot_hash = hashlib.sha256((root / "rules_snapshot.json").read_bytes()).hexdigest()
            if compliance.rules_snapshot_sha256 != snapshot_hash:
                errors.append("compliance.json: rules snapshot hash mismatch")
        if inquiry and seller and rules_snapshot and compliance.checked_at:
            from tradecase.compliance import evaluate_compliance

            try:
                expected = evaluate_compliance(
                    inquiry.model_dump(mode="json"), seller.model_dump(mode="json"),
                    [row.model_dump(mode="json") for row in rows], rules_snapshot.model_dump(mode="json"),
                    checked_at=compliance.checked_at,
                )
                if compliance.model_dump(mode="json") != expected:
                    errors.append("compliance.json: checks do not match recomputed compliance-v1 result")
            except ValueError as exc:
                errors.append(f"compliance.json: invalid rule derivation: {exc}")

    next_actions: NextActions | None = artifacts.get("next_actions.json")
    if next_actions:
        _duplicate_ids(next_actions.actions, "action_id", "next_actions.json", errors)
        for action in next_actions.actions:
            _references(action.evidence_ids, evidence, f"next_actions.json {action.action_id}", errors)

    review: DraftReview | None = artifacts.get("draft_review.json")
    if "reply_draft.md" in artifacts and review is None:
        errors.append("reply_draft.md: draft_review.json is required")
    if review:
        # Exact source bytes prevent a previously valid review from silently
        # following a changed seller record or a manually edited message.
        for name, expected_hash in ((review.draft_ref, review.draft_sha256),
                                    (review.input_ref, review.input_sha256),
                                    (review.seller_context_ref, review.seller_context_sha256)):
            try:
                if hashlib.sha256(safe_case_file(root, name).read_bytes()).hexdigest() != expected_hash:
                    errors.append(f"draft_review.json: stale {name} hash; regenerate draft")
            except (ValueError, OSError) as exc:
                errors.append(f"draft_review.json: stale source or draft: {exc}")
        if inquiry and seller:
            from tradecase.reporting import prepare_draft_review, prepare_next_actions, render_reply

            expected = prepare_draft_review(
                inquiry.model_dump(mode="json"), seller.model_dump(mode="json"),
                hashlib.sha256((root / "input.json").read_bytes()).hexdigest(),
                hashlib.sha256((root / "seller_context.json").read_bytes()).hexdigest(),
            )
            if review.model_dump(mode="json") != expected:
                errors.append("draft_review.json: stale or noncanonical preflight; regenerate draft")
            if artifacts.get("reply_draft.md") != render_reply(expected["message"], expected["is_synthetic"]):
                errors.append("draft_review.json: stale rendered reply; regenerate draft")
            expected_actions = prepare_next_actions(
                inquiry.model_dump(mode="json"), seller.model_dump(mode="json"),
                profile.model_dump(mode="json") if profile else None,
                assessment.model_dump(mode="json") if assessment else None,
                compliance.model_dump(mode="json") if compliance else None,
            )
            if not next_actions or next_actions.model_dump(mode="json") != expected_actions:
                errors.append("next_actions.json: does not match current draft follow-up derivation")

    if inquiry:
        for name, artifact in artifacts.items():
            values = artifact if isinstance(artifact, list) else [artifact]
            if isinstance(artifact, ComplianceResult):
                values = [artifact, *artifact.checks]
            if isinstance(artifact, RuleSet):
                values = artifact.rules
            for value in values:
                if hasattr(value, "is_synthetic") and value.is_synthetic and not inquiry.is_synthetic:
                    errors.append(f"{name}: synthetic data cannot be used in a real Case")
            if inquiry.is_synthetic and name in {
                "buyer_profile.json", "assessment.json", "compliance.json", "next_actions.json", "draft_review.json",
            } and not artifact.is_synthetic:
                errors.append(f"{name}: derived artifact must preserve synthetic Case flag")
        for reference in [inquiry.raw_source_ref, inquiry.seller_profile_ref]:
            if reference:
                try:
                    safe_case_file(root, reference)
                except ValueError as exc:
                    errors.append(f"input.json: {exc}")
    if manifest and manifest.state == "completed":
        if manifest.blockers or manifest.error:
            errors.append("manifest.json: completed state cannot retain blockers or error")
        if assessment and assessment.decision == "needs_review":
            errors.append("manifest.json: completed state contradicts assessment needs_review")
        if profile and (profile.unresolved_items or not profile.selected_candidate_id):
            errors.append("manifest.json: completed state contradicts unresolved buyer_profile")
        if compliance and any(check.status not in {"pass", "not_applicable"} for check in compliance.checks):
            errors.append("manifest.json: completed state contradicts unresolved or adverse compliance checks")
    return errors
