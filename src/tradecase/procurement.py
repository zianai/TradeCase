"""Conservative, evidence-bound procurement deadline interpretation."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tradecase.util import json_bytes

_DECLARATION = re.compile(
    r"(?:deadline on|bid submission deadline|deadline to receive proposals|proposal submission deadline|"
    r"submission deadline|deadline for submission|bid closing date|closing date|amended deadline|extended deadline)\s*[:：]",
    re.I,
)
_BODY = re.compile(
    r"\s*(?P<date>\d{4}-\d{2}-\d{2}|\d{1,2}-[A-Za-z]{3}-\d{4}|\d{1,2}\s+[A-Za-z]+\s+\d{4})"
    r"(?:\s*,?\s*(?:at\s+)?(?P<time>\d{1,2}:\d{2}))?"
    r"(?:\s*(?:\((?P<parenthesized>[^)]+)\)|(?P<plain>[A-Za-z][A-Za-z0-9_+./: -]*?)))?"
    r"\s*(?:Expired)?\s*$",
    re.I,
)
_ALIASES = {
    "jerusalem time": "Asia/Jerusalem",
    "london time": "Europe/London",
    "us eastern time": "America/New_York",
    "us central time": "America/Chicago",
    "us pacific time": "America/Los_Angeles",
    "beijing time": "Asia/Shanghai",
    "tokyo time": "Asia/Tokyo",
    "singapore time": "Asia/Singapore",
}
_MONTHS = {
    name: index
    for index, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        1,
    )
    for name in names
}


def _parse_day(value: str) -> datetime:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        year, month, day = map(int, value.split("-"))
    else:
        parts = value.split("-") if "-" in value else value.split()
        day, name, year = parts
        month = _MONTHS.get(name.casefold())
        if month is None:
            raise ValueError("unsupported month name")
        day, year = int(day), int(year)
    return datetime(year, month, day)


def _zone(value: str):
    value = value.strip()
    if value.upper() in {"UTC", "GMT"}:
        return timezone.utc
    match = re.fullmatch(r"(?:GMT|UTC)\s*([+-]?\d{1,2})(?:[.:](00|15|30|45))?", value, re.I)
    if match:
        hours, minutes = int(match.group(1)), int(match.group(2) or "00")
        if abs(hours) > 14 or (abs(hours) == 14 and minutes):
            raise ValueError("invalid GMT offset")
        sign = -1 if match.group(1).startswith("-") else 1
        return timezone(sign * timedelta(hours=abs(hours), minutes=minutes))
    zone_name = _ALIASES.get(value.casefold(), value)
    if not re.fullmatch(r"[A-Za-z_+-]+(?:/[A-Za-z0-9_+-]+)+", zone_name):
        raise ValueError("ambiguous or unsupported timezone")
    try:
        return ZoneInfo(zone_name)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError("timezone database unavailable or zone unknown") from exc


def _to_utc(local: datetime, zone) -> datetime:
    # Round-trip both folds: reject spring gaps and autumn overlaps instead of
    # selecting an arbitrary offset. Fixed-offset zones naturally deduplicate.
    options = set()
    for fold in (0, 1):
        candidate = local.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
        if candidate.astimezone(zone).replace(tzinfo=None) == local:
            options.add(candidate)
    if len(options) != 1:
        raise ValueError("ambiguous or nonexistent local time")
    return options.pop()


def evaluate_deadline(text: str, *, now: datetime) -> dict:
    """Parse explicit zones conservatively; a date-only notice is never open."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone aware")
    matches = list(_DECLARATION.finditer(text))
    if len(matches) != 1:
        return {
            "status": "needs_review",
            "deadline_utc": None,
            "reasons": ["conflicting_or_unparsed_deadline" if matches else "deadline_missing_or_unparsed"],
        }
    declaration = matches[0]
    end = text.find("\n", declaration.end())
    line = text[declaration.end() : end if end != -1 else len(text)].strip()
    match = _BODY.fullmatch(line)
    if not match:
        return {"status": "needs_review", "deadline_utc": None, "reasons": ["deadline_format_unparsed"]}
    try:
        day = _parse_day(match.group("date"))
        zone_text = match.group("parenthesized") or match.group("plain")
        if zone_text and zone_text.casefold() == "expired":
            zone_text = None
        if not zone_text:
            if not match.group("time"):
                # Any valid Python UTC offset is strictly less than 24 hours.
                # This loose upper bound does not guess a local zone or time.
                latest = (day + timedelta(days=2)).replace(tzinfo=timezone.utc)
                return {
                    "status": "expired" if now.astimezone(timezone.utc) >= latest else "needs_review",
                    "deadline_utc": None,
                    "latest_possible_utc": latest.isoformat().replace("+00:00", "Z"),
                    "reasons": ["date_only_timezone_unspecified", "conservative_utc_bound"],
                }
            raise ValueError("timezone missing")
        zone = _zone(zone_text)
        if not match.group("time"):
            latest = _to_utc(day + timedelta(days=1), zone)
            return {
                "status": "expired" if now.astimezone(timezone.utc) >= latest else "needs_review",
                "deadline_utc": None,
                "latest_possible_utc": latest.isoformat().replace("+00:00", "Z"),
                "reasons": ["date_only_time_unspecified"],
            }
        hour, minute = map(int, match.group("time").split(":"))
        local = day.replace(hour=hour, minute=minute)
        utc = _to_utc(local, zone)
    except (ValueError, OverflowError):
        return {"status": "needs_review", "deadline_utc": None, "reasons": ["invalid_deadline"]}
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
        declarations = list(_DECLARATION.finditer(text))
        cited = _DECLARATION.search(row["excerpt"])
        if not declarations or not cited:
            raise ValueError("deadline not present in cited excerpt")
        # Bind the complete cited declaration line, not merely its label.
        cited_end = row["excerpt"].find("\n", cited.start())
        cited_line = row["excerpt"][cited.start() : cited_end if cited_end != -1 else None].strip()
        source_lines = []
        for declaration in declarations:
            source_end = text.find("\n", declaration.start())
            source_lines.append(text[declaration.start() : source_end if source_end != -1 else None].strip())
        if cited_line not in source_lines or not re.search(r"\d", cited_line):
            raise ValueError("complete deadline statement not cited")
        basis = hashlib.sha256(json_bytes(row) + raw).hexdigest()
        parsed = evaluate_deadline(text, now=now or datetime.now(timezone.utc))
        # IANA data can change between environments. Bind the resolved instant
        # for named/date-only cases so a rule update invalidates old preflights.
        if parsed.get("latest_possible_utc") or (
            parsed.get("deadline_utc") and not re.search(r"\b(?:GMT|UTC)\s*[+-]?\d", cited_line, re.I)
        ):
            basis = hashlib.sha256(
                json_bytes(row)
                + raw
                + json_bytes(
                    {
                        "deadline_utc": parsed.get("deadline_utc"),
                        "latest_possible_utc": parsed.get("latest_possible_utc"),
                    }
                )
            ).hexdigest()
        result.update(parsed)
        result["basis_sha256"] = basis
    except (KeyError, ValueError, OSError, TypeError, json.JSONDecodeError):
        result["reasons"] = ["deadline_evidence_snapshot_mismatch"]
    return result
