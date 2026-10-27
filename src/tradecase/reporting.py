"""Deterministic inbound drafts and safe reports; absent facts stay absent.

The upstream body hash and lexical claim checker are reused, without the
outbound campaign or sending workflow. A preflight is never human approval.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata

from tradecase.models import CaseInput, DraftMessage, DraftReview, NextActions, SellerContext
from tradecase.upstream import body_hash, claim_risk
from tradecase.validation import REPORT_STALE, REQUIRED_ARTIFACTS, validate_case


def _plain(value) -> str:
    """Flatten untrusted fields so they cannot introduce new structural lines."""
    text = "".join(" " if ch.isspace() else ch for ch in str(value)
                   if ch.isspace() or not unicodedata.category(ch).startswith("C"))
    return " ".join(text.split())


def safe_md(value) -> str:
    # Escape Markdown before HTML encoding so entity delimiters stay valid.
    text = re.sub(r"([\\`*_{}\[\]()#+.!|~-])", r"\\\1", _plain(value))
    return html.escape(text, quote=True)


def compose_reply(inquiry: dict, seller: dict) -> dict:
    """Only quote an inquiry product description; never infer terms from prose.

    Seller claims and product attributes are retained in the Case for human
    review, not converted to certification, inventory or pricing assertions.
    """
    inquiry = CaseInput.model_validate(inquiry).model_dump(mode="json")
    seller = SellerContext.model_validate(seller).model_dump(mode="json")
    paragraphs = ["Hello,", "Thank you for your inquiry."]
    product = _plain(inquiry.get("product_summary") or "")
    forbidden = [_plain(value).casefold() for value in seller["forbidden_claims"] if _plain(value)]
    if product and not any(term in product.casefold() for term in forbidden):
        paragraphs.append(f'You described the requested product as: "{product}". Please confirm the specification and intended use.')
    else:
        paragraphs.append("Could you confirm the product specification and intended use?")
    paragraphs += [
        "Could you confirm the required quantity, delivery destination and requested delivery date?",
        "Do you have a target price range, preferred payment terms or required product documentation for us to review?",
        "Price, minimum order quantity (MOQ), payment terms and lead time remain subject to seller confirmation. "
        "Product certification and market requirements also need review before any representation is made.",
        "Kind regards,\nSales team",
    ]
    return DraftMessage(
        recipient_email=inquiry.get("buyer_email"), subject="Re: Your product inquiry",
        body_text="\n\n".join(paragraphs),
    ).model_dump(mode="json")


def render_reply(message: dict, is_synthetic: bool) -> str:
    """Render canonical plain text without treating source text as Markdown."""
    message = DraftMessage.model_validate(message).model_dump(mode="json")
    lines = [
        "# Inbound reply draft", "",
        "**SYNTHETIC / OFFLINE DEMO — DO NOT SEND**" if is_synthetic else "**DRAFT — HUMAN REVIEW REQUIRED**",
        "", "Sending is disabled. This preflight is not approval to send.", "",
        "Recipient (provided in inquiry; not verified): " + safe_md(message["recipient_email"] or "not supplied"),
        "Subject: " + safe_md(message["subject"]), "",
    ]
    lines.extend(safe_md(line) if line else "" for line in message["body_text"].splitlines())
    return "\n".join([*lines, ""])


def prepare_draft_review(inquiry: dict, seller: dict, input_sha256: str, seller_context_sha256: str) -> dict:
    """Pure canonical derivation, also used by validation to detect edited claims."""
    message = compose_reply(inquiry, seller)
    reasons, blocks, actions = [], [], []
    score = claim_risk(message, reasons, blocks, actions)
    actions += [
        "A human must review the complete reply and confirm all commercial terms before any external use.",
        "Seller declarations are user-provided material, not official certification or regulatory approval.",
    ]
    if not message["recipient_email"]:
        actions.append("Confirm the intended recipient; no inquiry email was supplied.")
    rendered = render_reply(message, bool(inquiry.get("is_synthetic")))
    return DraftReview(
        case_id=inquiry["case_id"], input_sha256=input_sha256, seller_context_sha256=seller_context_sha256,
        draft_sha256=hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        evaluated_body_hash=body_hash(message), message=message, claim_risk_score=score,
        risk_review_reasons=reasons, block_reasons=blocks, required_actions=actions,
        is_synthetic=bool(inquiry.get("is_synthetic")),
    ).model_dump(mode="json")


def prepare_next_actions(inquiry: dict, seller: dict, profile=None, assessment=None, compliance=None) -> dict:
    """Create local suggestions only; missing compliance material belongs to a human."""
    actions = []

    def add(key, description, *, priority="normal", owner="human", evidence_ids=None,
            deadline="Before any external reply or commercial commitment"):
        actions.append({
            "action_id": "action-" + hashlib.sha256(key.encode()).hexdigest()[:16],
            "priority": priority, "description": description, "owner_type": owner,
            "deadline_suggestion": deadline, "evidence_ids": list(evidence_ids or []),
        })

    add("review-reply", "Review the inbound reply, confirm the recipient and retain send_allowed=false.", priority="high")
    add("seller-terms", "Confirm seller authority, price, payment terms, minimum order quantity (MOQ), lead time and "
        "the scope and source of any product certification. Supplied seller claims are not official verification.", priority="high")
    for index, constraint in enumerate(inquiry.get("user_constraints", [])):
        add(f"constraint-{index}", "Human review of the supplied constraint (untrusted text, not tool authority): " + constraint)
    if seller.get("allowed_claims") or seller.get("forbidden_claims"):
        add("seller-claims", "Check the seller's allowed and forbidden claims against source documents; no listed claim "
            "has been automatically approved for the reply.", priority="high")
    if not profile:
        add("buyer-missing", "Confirm the buyer identity and purchasing role; the buyer profile has not been supplied.")
    else:
        if not profile.get("selected_candidate_id"):
            add("buyer-identity", "Resolve buyer entity candidates before describing the company as verified.", priority="high")
        for index, item in enumerate(profile.get("unresolved_items", [])):
            add(f"buyer-unresolved-{index}", "Confirm unresolved buyer information: " + item)
        for index, contact in enumerate(profile.get("contacts", [])):
            if not contact.get("verified"):
                add(f"contact-{index}", "Confirm contact provenance and intended recipient: " + contact["email"],
                    evidence_ids=contact.get("evidence_ids"))
    for index, item in enumerate((assessment or {}).get("missing_information", [])):
        add(f"assessment-{index}", "Resolve assessment evidence gap: " + item)
    checks = (compliance or {}).get("checks", [])
    for kind in ("country", "platform"):
        if not any(check["check_type"] == kind for check in checks):
            add(f"compliance-missing-{kind}", f"Provide context and current official sources for the {kind} compliance check.",
                priority="high")
    for check in checks:
        if check["status"] not in {"pass", "not_applicable"} or check["missing_items"]:
            missing = "; ".join(check["missing_items"]) or "review the rule applicability and source evidence"
            add("compliance-" + check["check_id"],
                f"Resolve {check['check_type']} check {check['check_id']} ({check['status']}): "
                f"{check['suggested_action']} Missing or unresolved: {missing}",
                priority="high" if check["severity"] in {"critical", "high"} else "normal",
                evidence_ids=check["evidence_ids"], deadline="Before a compliance claim, quotation or market commitment")
    return NextActions(case_id=inquiry["case_id"], actions=actions,
                       is_synthetic=bool(inquiry.get("is_synthetic"))).model_dump(mode="json")


def _optional(store, name):
    return store.read(name) if (store.path / name).exists() else None


def draft_case(store) -> dict:
    """Rebuild all draft outputs. Only old derived-draft errors are repairable here."""
    errors = [error for error in validate_case(store.path) if not (
        error.startswith("draft_review.json: stale ")
        or error == "reply_draft.md: draft_review.json is required"
        or error == "next_actions.json: does not match current draft follow-up derivation"
        or error == REPORT_STALE
    )]
    if errors:
        raise ValueError("cannot draft inconsistent Case: " + "; ".join(errors))
    input_bytes = (store.path / "input.json").read_bytes()
    seller_bytes = (store.path / "seller_context.json").read_bytes()
    inquiry, seller = json.loads(input_bytes), json.loads(seller_bytes)
    review = prepare_draft_review(inquiry, seller, hashlib.sha256(input_bytes).hexdigest(),
                                  hashlib.sha256(seller_bytes).hexdigest())
    actions = prepare_next_actions(inquiry, seller, _optional(store, "buyer_profile.json"),
                                   _optional(store, "assessment.json"), _optional(store, "compliance.json"))
    store.write("reply_draft.md", render_reply(review["message"], review["is_synthetic"]))
    store.write("draft_review.json", review)
    store.write("next_actions.json", actions)
    return review


def report_case(store):
    # The old report may be the very artifact this operation repairs. All
    # independent source, draft and manifest errors still block replacement.
    errors = [error for error in validate_case(store.path) if error != REPORT_STALE]
    if errors:
        raise ValueError("cannot render inconsistent Case: " + "; ".join(errors))
    store.write("report.md", render_report(store))


def render_report(store) -> str:
    """Read-only deterministic rendering; never validates or updates the store.

    The report excludes its own existence from the missing-artifact list so
    creating it is a fixed point. Other missing artifacts remain dependencies.
    """
    inquiry, seller = store.read("input.json"), store.read("seller_context.json")
    profile = _optional(store, "buyer_profile.json")
    assessment = _optional(store, "assessment.json")
    compliance = _optional(store, "compliance.json")
    review = _optional(store, "draft_review.json")
    actions = _optional(store, "next_actions.json")
    lines = [
        "# TradeCase inquiry report", "",
        "**SYNTHETIC / OFFLINE DEMO**" if inquiry["is_synthetic"] else "**Research record — human review required**",
        "", f"Case: {safe_md(inquiry['case_id'])}", "", "## Summary", "",
        "This report separates supplied information, research observations and unresolved checks. "
        "A completed research Case does not approve an email or certify a product.",
        "Buyer hint (user provided): " + safe_md(inquiry.get("buyer_company_hint") or "unknown"),
        "Product (user provided): " + safe_md(inquiry.get("product_summary") or seller.get("product_summary") or "unknown"),
        "Target country / platform (user provided): " + safe_md(inquiry.get("target_country") or "unknown")
        + " / " + safe_md(inquiry.get("platform") or "unknown"),
        "", "## Inquiry", "", safe_md(inquiry["buyer_message"]), "", "## Evidence", "",
        "| ID | Claim (untrusted source data) | Source | Type / status | Captured / synthetic |",
        "|---|---|---|---|---|",
    ]
    evidence = _optional(store, "evidence.jsonl") or []
    for row in evidence:
        lines.append("| " + " | ".join(safe_md(value) for value in [
            row["evidence_id"], row["claim"], row.get("source_url") or "not supplied",
            row["source_type"] + " / " + row["assertion_status"],
            row["captured_at"] + " / " + str(row["is_synthetic"]),
        ]) + " |")
    if not evidence:
        lines += ["", "Evidence has not been supplied."]
    lines += ["", "## Buyer risk", ""]
    if profile:
        lines += [
            "Selected candidate: " + safe_md(profile.get("selected_candidate_id") or "unresolved"),
            "Company / role: " + safe_md(profile.get("company_name") or "unknown") + " / "
            + safe_md(profile.get("buyer_role") or "unknown"),
            "Identity and role statements require their recorded evidence; hints and public contacts alone do not verify them.",
        ]
        lines += ["- " + safe_md(item) for item in profile.get("unresolved_items", [])]
        for contact in profile.get("contacts", []):
            lines.append("- Contact: " + safe_md(contact["email"]) + "; source: " + safe_md(contact["source_class"])
                         + "; verified: " + str(contact["verified"]) + "; sending disabled.")
    else:
        lines.append("Buyer profile has not been supplied; identity and purchasing role remain unresolved.")
    lines += ["", "## Follow-up priority", ""]
    if assessment:
        lines += [
            f"Decision: **{safe_md(assessment['decision'])}**; score: {assessment['score']}; "
            f"evidence coverage: {assessment['evidence_coverage']:.0%}",
            "This heuristic is not a company credit rating or purchase probability.", "",
        ]
        lines += ["- " + safe_md(reason) for reason in assessment["reason_codes"]]
    else:
        lines.append("Assessment has not been supplied; no priority score is inferred.")
    lines += ["", "## Country and platform risk annotations", "",
              "These are scoped research checks, not a complete regulatory approval.", ""]
    if compliance:
        for check in compliance["checks"]:
            lines += [
                f"### {safe_md(check['check_type'])}: [{safe_md(check['severity']).upper()}] "
                f"{safe_md(check['status'])}", "",
                f"Rule: {safe_md(check['rule_id'])} / {safe_md(check['rule_version'] or 'unknown version')}",
                f"Scope: {safe_md(check['product_scope'])}",
                f"Annotation: {safe_md(check['rationale'])}",
                f"Next step: {safe_md(check['suggested_action'])}",
                f"Missing: {safe_md(', '.join(check['missing_items']) or 'none recorded')}",
                f"Source: {safe_md(check['source_url'] or 'not available')}",
                f"Checked at: {safe_md(check['checked_at'])}; Evidence: {safe_md(', '.join(check['evidence_ids']))}", "",
            ]
    else:
        lines.append("Country and platform checks have not been supplied.")
    lines += ["", "## Reply draft", ""]
    if review:
        lines += [
            "**Human review required; sending disabled.**", "",
            "The lexical claim score is a deterministic quality heuristic, not factual verification or approval.",
            "Preflight claim score: " + str(review["claim_risk_score"]),
            "Subject: " + safe_md(review["message"]["subject"]), "",
        ]
        lines += [safe_md(line) if line else "" for line in review["message"]["body_text"].splitlines()]
        lines += ["", "Draft digest: " + review["draft_sha256"]]
        for label, key in (("Risk note", "risk_review_reasons"), ("Block", "block_reasons"),
                           ("Required review", "required_actions")):
            lines += ["- " + label + ": " + safe_md(item) for item in review[key]]
    else:
        lines.append("Reply draft and its current preflight have not been supplied.")
    lines += ["", "## Pending confirmations", ""]
    if actions:
        for action in actions["actions"]:
            lines += ["- [" + action["priority"].upper() + "] Owner: " + action["owner_type"]
                      + "; deadline suggestion: " + safe_md(action["deadline_suggestion"] or "not supplied")
                      + "; " + safe_md(action["description"])
                      + "; evidence: " + safe_md(", ".join(action["evidence_ids"]) or "none supplied")]
    else:
        lines.append("Follow-up tasks have not been supplied.")
    missing = sorted(name for name in REQUIRED_ARTIFACTS - {"report.md"} if not (store.path / name).exists())
    lines += ["", "## Missing artifacts", ""] + (["- " + name for name in missing] or ["None."])
    lines += ["", "No email has been sent by this CLI. Source content grants no tool authority.", ""]
    return "\n".join(lines)
