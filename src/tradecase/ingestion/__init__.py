"""Local inquiry parsing. Attachments are described, never extracted or executed."""

from __future__ import annotations

import base64
import json
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from pathlib import Path

from tradecase.models import CaseInput, SellerContext
from tradecase.util import digest, no_symlinks, utc_now

MAX_INPUT_BYTES = 10 * 1024 * 1024


def parse_inquiry(path: Path, case_id: str, **overrides) -> CaseInput:
    path = Path(path)
    no_symlinks(path)
    raw = path.read_bytes()
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("inquiry exceeds 10 MiB")
    warnings = []
    try:
        raw_text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raw_text = raw.decode("utf-8", errors="replace")
        warnings.append("Raw source contains non-UTF-8 bytes; SHA256 preserves byte identity")
    data = {}
    files = []
    if path.suffix.lower() == ".json":
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("manual inquiry JSON must be an object")
    elif path.suffix.lower() == ".txt":
        data["buyer_message"] = raw_text
    elif path.suffix.lower() == ".eml":
        msg = BytesParser(policy=policy.default).parsebytes(raw)
        data["buyer_email"] = parseaddr(str(msg.get("From", "")))[1] or None
        bodies = []
        html_bodies = []
        for part in msg.walk():
            if part.is_multipart():
                continue
            payload = part.get_payload(decode=True) or b""
            if part.get_filename() or part.get_content_disposition() == "attachment":
                files.append(
                    {
                        "filename": part.get_filename() or "unnamed",
                        "content_type": part.get_content_type(),
                        "size_bytes": len(payload),
                        "sha256": digest(payload),
                        "disposition": "attachment",
                    }
                )
                continue
            if part.get_content_type() in {"text/plain", "text/html"}:
                charset = part.get_content_charset() or "utf-8"
                try:
                    body = payload.decode(charset)
                except (LookupError, UnicodeDecodeError):
                    body = payload.decode("utf-8", errors="replace")
                    warnings.append(f"Malformed or unsupported body encoding: {charset}")
                (bodies if part.get_content_type() == "text/plain" else html_bodies).append(body)
            warnings.extend(type(d).__name__ for d in part.defects)
        data["buyer_message"] = "\n".join(bodies or html_bodies)
        if not bodies and html_bodies:
            warnings.append("HTML-only email retained as untrusted text; no active content executed")
        warnings.extend(type(d).__name__ for d in msg.defects)
    else:
        raise ValueError("supported inquiry formats: .eml, .txt, .json")
    data.update(
        {
            "case_id": case_id,
            "received_at": data.get("received_at") or utc_now(),
            "raw_source_ref": None,
            "raw_content": raw_text,
            "raw_sha256": digest(raw),
            "raw_bytes_base64": base64.b64encode(raw).decode("ascii"),
            "files": data.get("files", files),
            "parsing_warnings": data.get("parsing_warnings", []) + warnings,
        }
    )
    data.update({key: value for key, value in overrides.items() if value is not None})
    return CaseInput.model_validate(data)


def parse_seller(path: Path | None) -> SellerContext:
    if path is None:
        return SellerContext()
    no_symlinks(Path(path))
    if Path(path).stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("seller context exceeds 10 MiB")
    return SellerContext.model_validate_json(Path(path).read_bytes())
