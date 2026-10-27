#!/usr/bin/env python3
"""Retained upstream draft/hash helpers; all SMTP sending is disabled in V1.

The original sending implementation is preserved in Git history. There is no
configuration flag that re-enables sending in TradeCase V1.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlparse

try:  # Package use in TradeCase; preserve direct script execution.
    from .contracts import (
        ContractError,
        validate_approved_outreach,
        validate_outreach_evaluation,
        validate_sent_log_event,
    )
except ImportError:
    from contracts import (
        ContractError,
        validate_approved_outreach,
        validate_outreach_evaluation,
        validate_sent_log_event,
    )

SEND_DISABLED_MESSAGE = "Email sending is disabled in TradeCase V1; create a draft for human review."

SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SMTP_CONFIG = SKILL_DIR / "_shared" / "smtp-config.json"
SMTP_CONFIG_ENV = "B2B_LEAD_HUNTER_SMTP_CONFIG"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def append_jsonl(path: Path, rows: list[dict]) -> None:
    for i, row in enumerate(rows, start=1):
        validate_sent_log_event(row, f"sent-log-event[{i}]")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def normalized_domain(value: str) -> str:
    text = (value or "").strip().lower()
    if not text:
        return ""
    if "://" not in text:
        text = "https://" + text
    host = urlparse(text).netloc.lower()
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    if host.startswith("www."):
        host = host[4:]
    return host.split(":", 1)[0]


def normalized_company(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def body_hash(draft: dict) -> str:
    payload = "\n".join(
        [
            str(draft.get("recipient_email") or "").strip().lower(),
            str(draft.get("subject") or ""),
            str(draft.get("body_text") or ""),
            str(draft.get("opt_out_line") or ""),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def event_id(draft: dict, event_type: str, timestamp: str) -> str:
    seed = "|".join([event_type, str(draft.get("draft_id") or ""), str(draft.get("recipient_email") or ""), timestamp])
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def load_suppressions(path: Path | None) -> dict[str, set[str]]:
    out = {"email": set(), "domain": set(), "company": set()}
    if not path or not path.exists():
        return out
    with path.open("r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            typ = str(row.get("type") or "").strip().lower()
            value = str(row.get("value") or "").strip().lower()
            if typ == "email" and value:
                out["email"].add(value)
            elif typ == "domain" and value:
                out["domain"].add(normalized_domain(value))
            elif typ == "company" and value:
                out["company"].add(normalized_company(value))
    return out


def sent_domains(log_rows: list[dict]) -> set[str]:
    out = set()
    for row in log_rows:
        if row.get("event_type") == "send_success" and row.get("result") == "ok":
            domain = normalized_domain(str(row.get("company_domain") or ""))
            if domain:
                out.add(domain)
    return out


def load_passed_evaluations(path: Path) -> dict[str, dict]:
    rows = read_jsonl(path)
    out: dict[str, dict] = {}
    for i, row in enumerate(rows, start=1):
        validate_outreach_evaluation(row, f"outreach-evaluations[{i}]")
        if row.get("decision") == "pass":
            out[str(row.get("draft_id") or "")] = row
    return out


def make_log(draft: dict, event_type: str, result: str, error: str = "", message_id: str = "", smtp_response: str = "") -> dict:
    ts = now_iso()
    return {
        "event_id": event_id(draft, event_type, ts),
        "event_type": event_type,
        "draft_id": str(draft.get("draft_id") or ""),
        "lead_id": str(draft.get("lead_id") or ""),
        "recipient_email": str(draft.get("recipient_email") or "").strip().lower(),
        "company_domain": normalized_domain(str(draft.get("company_domain") or draft.get("website") or "")),
        "subject": str(draft.get("subject") or ""),
        "approved_body_hash": str(draft.get("approved_body_hash") or ""),
        "message_id": message_id,
        "smtp_response": smtp_response,
        "timestamp": ts,
        "result": result,
        "error": error,
    }


def suppression_reason(draft: dict, suppressions: dict[str, set[str]]) -> str:
    email = str(draft.get("recipient_email") or "").strip().lower()
    domain = normalized_domain(str(draft.get("company_domain") or draft.get("website") or ""))
    company = normalized_company(str(draft.get("company_name") or ""))
    email_domain = email.rsplit("@", 1)[-1] if "@" in email else ""
    if email and email in suppressions["email"]:
        return "recipient email is suppressed"
    if email_domain and email_domain in suppressions["domain"]:
        return "recipient email domain is suppressed"
    if domain and domain in suppressions["domain"]:
        return "company domain is suppressed"
    if company and company in suppressions["company"]:
        return "company is suppressed"
    return ""


def validate_draft(
    draft: dict,
    suppressions: dict[str, set[str]],
    already_sent: set[str],
    passed_evaluations: dict[str, dict],
    path: str,
) -> tuple[str, str]:
    validate_approved_outreach(draft, path)
    draft_id = str(draft.get("draft_id") or "")
    if draft_id not in passed_evaluations:
        return "evaluation_missing", "missing passing outreach evaluation for draft_id"
    evaluation = passed_evaluations[draft_id]
    if draft.get("approval_status") != "approved":
        return "approval_missing", "approval_status is not approved"
    if draft.get("state") != "approved":
        return "approval_missing", "state is not approved"
    if draft.get("send_recommendation") != "send":
        return "approval_missing", "send_recommendation is not send"
    if draft.get("recipient_type") == "inferred":
        return "approval_missing", "inferred recipient is not sendable"
    if draft.get("language_confidence") != "high":
        return "approval_missing", "language_confidence is not high"
    if any(isinstance(c, dict) and c.get("risk") == "high" for c in draft.get("claims_made", []) or []):
        return "approval_missing", "claims_made contains high risk claim"
    expected = body_hash(draft)
    if str(evaluation.get("evaluated_body_hash") or "") != expected:
        return "evaluation_missing", "passing evaluation hash does not match approved draft body"
    if str(draft.get("approved_body_hash") or "") != expected:
        return "hash_mismatch", "approved_body_hash does not match recipient/subject/body/opt-out"
    suppressed = suppression_reason(draft, suppressions)
    if suppressed:
        return "suppressed", suppressed
    domain = normalized_domain(str(draft.get("company_domain") or draft.get("website") or ""))
    if domain and domain in already_sent:
        return "duplicate_skipped", "company already has a successful first-touch send"
    return "", ""


def build_message(draft: dict, cfg: dict) -> EmailMessage:
    msg = EmailMessage()
    from_email = str(cfg.get("from_email") or cfg.get("username") or "").strip()
    from_name = str(cfg.get("from_name") or "").strip()
    msg["From"] = f"{from_name} <{from_email}>" if from_name else from_email
    msg["To"] = str(draft.get("recipient_email") or "").strip()
    msg["Subject"] = str(draft.get("subject") or "").strip()
    if cfg.get("reply_to"):
        msg["Reply-To"] = str(cfg["reply_to"]).strip()
    msg.set_content(str(draft.get("body_text") or ""))
    return msg


def send_message(msg: EmailMessage, cfg: dict) -> tuple[str, str]:
    """Fail before inspecting the configuration, credentials or message."""
    raise RuntimeError(SEND_DISABLED_MESSAGE)


def resolve_smtp_config(path: Path | None) -> Path:
    if path:
        return path
    env_path = os.environ.get(SMTP_CONFIG_ENV, "").strip()
    if env_path:
        return Path(env_path)
    return DEFAULT_SMTP_CONFIG


def main() -> int:
    """Disable the legacy CLI, including --send-approved and --dry-run."""
    print(SEND_DISABLED_MESSAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ContractError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
