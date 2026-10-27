"""Conservative, evidence-bound procurement deadline interpretation."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tradecase.util import json_bytes

_PRIMARY = re.compile(
    r"Deadline on:\s*(\d{1,2}-[A-Za-z]{3}-\d{4})\s+(\d{1,2}:\d{2})\s*"
    r"\(GMT\s*([+-]?\d{1,2})(?:\.(00|30|45))?\)",
    re.I,
)
_SECONDARY = re.compile(
    r"(?:bid submission deadline|deadline to receive proposals|proposal submission deadline)\s*:", re.I
)


def evaluate_deadline(text: str, *, now: datetime) -> dict:
    """Only parse an explicit numeric GMT offset; ambiguity never becomes open."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone aware")
    matches = list(_PRIMARY.finditer(text))
    if len(matches) != 1 or _SECONDARY.search(text):
        return {
            "status": "needs_review",
            "deadline_utc": None,
            "reasons": ["conflicting_or_unparsed_deadline" if matches else "deadline_missing_or_unparsed"],
        }
    match = matches[0]
    try:
        hours = int(match.group(3))
        minutes = int(match.group(4) or "00")
        if abs(hours) > 14 or (abs(hours) == 14 and minutes):
            raise ValueError("invalid GMT offset")
        sign = -1 if match.group(3).startswith("-") else 1
        offset = timezone(sign * timedelta(hours=abs(hours), minutes=minutes))
        due = datetime.strptime(match.group(1) + " " + match.group(2), "%d-%b-%Y %H:%M").replace(tzinfo=offset)
    except ValueError:
        return {"status": "needs_review", "deadline_utc": None, "reasons": ["invalid_deadline"]}
    utc = due.astimezone(timezone.utc)
    return {
        "status": "expired" if now.astimezone(timezone.utc) >= utc else "open",
        "deadline_utc": utc.isoformat().replace("+00:00", "Z"),
        "reasons": [],
    }


def is_procurement(inquiry: dict) -> bool:
    """Preserve a fail-closed path for the five pre-existing P7 notice Cases."""
    return (
        inquiry.get("case_type") == "procurement"
        or bool(inquiry.get("deadline_evidence_id"))
        or any(
            warning.startswith("Public procurement notice excerpt;") for warning in inquiry.get("parsing_warnings", [])
        )
    )


def case_deadline(root: Path, inquiry: dict, evidence: list[dict], *, now: datetime | None = None) -> dict | None:
    """Bind supported evidence and an indexed source snapshot; never fetch content."""
    if not is_procurement(inquiry):
        return None
    result = {
        "status": "needs_review",
        "deadline_utc": None,
        "reasons": ["deadline_evidence_missing"],
        "evidence_id": inquiry.get("deadline_evidence_id"),
        "basis_sha256": None,
    }
    rows = [row for row in evidence if row["evidence_id"] == inquiry.get("deadline_evidence_id")]
    if len(rows) != 1:
        return result
    row = rows[0]
    if (
        not row.get("source_url")
        or row["assertion_status"] != "supported"
        or row["source_type"]
        not in {
            "official_site",
            "government",
            "platform_official",
        }
    ):
        result["reasons"] = ["deadline_source_unverified"]
        return result
    ref = row.get("local_snapshot_ref")
    if not ref:
        result["reasons"] = ["deadline_snapshot_missing"]
        return result
    from tradecase.validation import safe_case_file

    try:
        raw = safe_case_file(root, ref).read_bytes()
        manifest = json.loads(safe_case_file(root, "manifest.json").read_bytes())
        if manifest.get("artifact_index", {}).get(ref) != hashlib.sha256(raw).hexdigest():
            raise ValueError("source snapshot is unindexed or changed")
        captured = json.loads(raw)
        text = captured["selected_lines"]
        if (
            not isinstance(text, str)
            or captured["source_url"] != row["source_url"]
            or not row.get("excerpt")
            or row["excerpt"] not in text
        ):
            raise ValueError("source or excerpt mismatch")
        # The deadline must itself be contained in the cited excerpt, not merely
        # somewhere else on a matching domain or in an unrelated snapshot.
        if not _PRIMARY.search(row["excerpt"]):
            raise ValueError("deadline not present in cited excerpt")
        basis = hashlib.sha256(json_bytes(row) + raw).hexdigest()
        result.update(evaluate_deadline(text, now=now or datetime.now(timezone.utc)))
        result["basis_sha256"] = basis
    except (KeyError, ValueError, OSError, TypeError, json.JSONDecodeError):
        result["reasons"] = ["deadline_evidence_snapshot_mismatch"]
    return result
