"""P7 deterministic permission and reservation boundary; never an approval tool.

An OS operator installs a private grant and pins its SHA in process configuration.
Business/Agent input cannot install a grant, change that pin, or reconcile receipts.
Each product owns its own directory and SQLite ledger. No business state is shared.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from pathlib import Path


class PolicyDenied(RuntimeError):
    pass


def digest(value):
    raw = (
        value
        if isinstance(value, bytes)
        else json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    )
    return hashlib.sha256(raw).hexdigest()


def money(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > 10000:
            raise ValueError()
        return int((amount * 1000000).to_integral_value(rounding=ROUND_CEILING))
    except (InvalidOperation, ValueError, TypeError):
        raise PolicyDenied("INVALID_PRICE_CEILING") from None


def timestamp(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError()
        return result
    except (ValueError, TypeError, AttributeError):
        raise PolicyDenied("INVALID_TIMESTAMP") from None


class ValidationRunPolicy:
    ACTIONS = {"read_external", "submit_model", "generate_image", "vision_review", "inspect_customer_data"}

    def __init__(self, root, system, approved_sha="", enabled=False):
        self.root = Path(root).absolute() if root else None
        self.system, self.approved_sha, self.enabled = system, approved_sha, enabled

    @classmethod
    def from_env(cls, system):
        prefix = system.upper()
        return cls(
            os.getenv(prefix + "_P7_ROOT"),
            system,
            os.getenv(prefix + "_P7_APPROVED_GRANT_SHA256", ""),
            os.getenv("ALLOW_TEST_LIVE") == "on",
        )

    def _private(self, name):
        if self.root is None or self.root != self.root.resolve():
            raise PolicyDenied("ISOLATION_REQUIRED")
        path = self.root / name
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise PolicyDenied("PRIVATE_OPERATOR_RECORD_REQUIRED")
        raw = path.read_bytes()
        if len(raw) > 65536:
            raise PolicyDenied("RECORD_SIZE")
        return raw

    def context(self):
        try:
            return json.loads(self._private("context.json"))
        except (ValueError, OSError):
            raise PolicyDenied("RUN_CONTEXT_REQUIRED") from None

    def validate(self, request, upper_usd):
        if request.get("action") not in self.ACTIONS:
            raise PolicyDenied("EXTERNAL_WRITES_FORBIDDEN")
        if not self.enabled or not self.approved_sha:
            raise PolicyDenied("AUTH_REQUIRED")
        raw = self._private("grant.json")
        if digest(raw) != self.approved_sha:
            raise PolicyDenied("APPROVAL_HASH_MISMATCH")
        try:
            grant = json.loads(raw)
            isolation = json.loads(self._private("isolation.json"))
            now = datetime.now(timezone.utc)
            if grant["revoked_at_utc"] or (self.root / "revoked").exists():
                raise PolicyDenied("AUTH_REVOKED")
            if not timestamp(grant["approved_at_utc"]) <= now < timestamp(grant["expires_at_utc"]):
                raise PolicyDenied("AUTH_EXPIRED")
            if grant["actor_origin"] != "operator" or not grant["actor_id"] or not grant["human_reason"]:
                raise PolicyDenied("HUMAN_AUTH_REQUIRED")
            if grant["environment"] != "live_sandbox" or grant["allow_external_writes"] is not False:
                raise PolicyDenied("ENVIRONMENT_DENIED")
            for field in ("run_id", "system", "tenant_id", "environment"):
                if isolation[field] != request[field] or grant[field] != request[field]:
                    raise PolicyDenied("SCOPE_MISMATCH")
            if grant["system"] != self.system or isolation["data_root"] != str(self.root):
                raise PolicyDenied("ISOLATION_REQUIRED")
            for field in ("case_id", "dataset_id", "plan_hash", "input_hash", "rights_hash", "provider_config_hash"):
                if request[field] != grant[field] or not request[field]:
                    raise PolicyDenied("SUBJECT_MISMATCH")
            for field in ("plan_hash", "input_hash", "rights_hash", "provider_config_hash"):
                if len(request[field]) != 64 or any(c not in "0123456789abcdef" for c in request[field]):
                    raise PolicyDenied("INVALID_HASH")
            if request["rights_current"] is not True:
                raise PolicyDenied("RIGHTS_REVOKED")
            if request["data_classification"] not in grant["data_classifications"]:
                raise PolicyDenied("DATA_SCOPE_DENIED")
            if not grant["export_allowed"]:
                raise PolicyDenied("DATA_EXPORT_DENIED")
            capability = grant["capabilities"][request["action"]]
            for field in ("provider", "model", "domain"):
                if request[field] != capability[field] or not request[field]:
                    raise PolicyDenied("CAPABILITY_CHANGED")
            if any(
                type(capability[k]) is not int or capability[k] < 0
                for k in ("max_requests", "max_images", "max_attempts")
            ):
                raise PolicyDenied("INVALID_LIMIT")
            if capability["max_attempts"] != 1:
                raise PolicyDenied("AUTOMATIC_RETRY_NOT_AUTHORIZED")
            if upper_usd is None or money(upper_usd) > money(capability["max_usd"]):
                raise PolicyDenied("BUDGET_EXCEEDED")
            if request["action"] in {"submit_model", "generate_image", "vision_review"} and money(upper_usd) <= 0:
                raise PolicyDenied("PRICE_CEILING_REQUIRED")
            return grant, capability
        except (KeyError, TypeError, ValueError):
            raise PolicyDenied("AUTH_RECORD_INVALID") from None

    def preflight(self, request, upper_usd, token_present=False):
        # Never echo arbitrary request fields, URLs, prompts, exception messages, or credentials.
        cap = None
        try:
            _, cap = self.validate(request, upper_usd)
            path = self.root / "reservations.sqlite"
            if path.is_symlink():
                raise PolicyDenied("ISOLATION_REQUIRED")
            if path.exists():
                with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
                    if db.execute(
                        "SELECT 1 FROM calls WHERE grant_hash=? AND status IN ('reserved','reconciling')",
                        (self.approved_sha,),
                    ).fetchone():
                        raise PolicyDenied("UNRESOLVED_RECEIPT")
                    count, spent = db.execute(
                        "SELECT count(*),coalesce(sum(max(reserved,coalesce(observed,0))),0) FROM calls WHERE grant_hash=? AND action=?",
                        (self.approved_sha, request["action"]),
                    ).fetchone()
                    if count >= cap["max_requests"] or spent + money(upper_usd) > money(cap["max_usd"]):
                        raise PolicyDenied("BUDGET_EXCEEDED")
            elif cap["max_requests"] == 0:
                raise PolicyDenied("BUDGET_EXCEEDED")
            status, reasons = "allowed", []
        except (PolicyDenied, OSError, sqlite3.Error) as exc:
            status, reasons = "blocked", [str(exc) if isinstance(exc, PolicyDenied) else "PRIVATE_RECORD_UNAVAILABLE"]
        return {
            "system": self.system,
            "configuration": {
                "provider": request.get("provider")
                if request.get("provider") in {"openai", "public_web", "stub"}
                else "redacted",
                "model": request.get("model")
                if re.fullmatch(r"(?:gpt-|o[1-9]-|chatgpt-|stub-)[a-z0-9._-]{1,80}", str(request.get("model", "")))
                else "redacted_or_unselected",
                "required_domain": "api.openai.com" if request.get("provider") == "openai" else "operator_allowlist",
                "capability_verified_live": False,
                "environment": "live_sandbox",
                "data_classification": request.get("data_classification")
                if request.get("data_classification")
                in {"synthetic", "public", "redacted_business", "sensitive_business"}
                else "redacted",
                "action": request.get("action") if request.get("action") in self.ACTIONS else "forbidden",
            },
            "approved_limits": None
            if cap is None
            else {
                "max_requests": cap["max_requests"],
                "max_images": cap["max_images"],
                "max_attempts": cap["max_attempts"],
                "max_usd": money(cap["max_usd"]) / 1000000,
            },
            "status": status,
            "reasons": reasons,
            "token_present": bool(token_present),
            "external_writes": False,
            "live_executed": False,
            "approved_grant_sha256": self.approved_sha,
        }

    def _db(self):
        if self.root is None:
            raise PolicyDenied("ISOLATION_REQUIRED")
        path = self.root / "reservations.sqlite"
        if path.is_symlink():
            raise PolicyDenied("ISOLATION_REQUIRED")
        db = sqlite3.connect(path, timeout=30, isolation_level=None)
        os.chmod(path, 0o600)
        db.execute("PRAGMA busy_timeout=30000")
        db.execute(
            "CREATE TABLE IF NOT EXISTS calls (id TEXT PRIMARY KEY, grant_hash TEXT, action TEXT, subject TEXT, status TEXT, reserved INTEGER, observed INTEGER, images INTEGER, basis TEXT)"
        )
        return db

    def reserve(self, request_id, request, upper_usd, images=0):
        if not request_id or len(request_id) > 200 or type(images) is not int or images < 0:
            raise PolicyDenied("INVALID_REQUEST")
        self.validate(request, upper_usd)
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            _, cap = self.validate(request, upper_usd)
            if db.execute("SELECT 1 FROM calls WHERE id=?", (request_id,)).fetchone():
                raise PolicyDenied("ALREADY_RESERVED_RECONCILE")
            if db.execute(
                "SELECT 1 FROM calls WHERE grant_hash=? AND status IN ('reserved','reconciling')", (self.approved_sha,)
            ).fetchone():
                raise PolicyDenied("UNRESOLVED_RECEIPT")
            count, spent, used_images = db.execute(
                "SELECT count(*),coalesce(sum(max(reserved,coalesce(observed,0))),0),coalesce(sum(images),0) FROM calls WHERE grant_hash=? AND action=?",
                (self.approved_sha, request["action"]),
            ).fetchone()
            if (
                count + 1 > cap["max_requests"]
                or spent + money(upper_usd) > money(cap["max_usd"])
                or used_images + images > cap["max_images"]
            ):
                raise PolicyDenied("BUDGET_EXCEEDED")
            db.execute(
                "INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    request_id,
                    self.approved_sha,
                    request["action"],
                    digest(request),
                    "reserved",
                    money(upper_usd),
                    None,
                    images,
                    "unknown",
                ),
            )
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def settle(self, request_id, observed_usd=None, basis="unknown"):
        if basis not in {"actual", "estimated", "unknown"}:
            raise PolicyDenied("INVALID_COST_BASIS")
        if (basis == "unknown") != (observed_usd is None):
            raise PolicyDenied("UNKNOWN_COST_IS_NOT_ZERO")
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT status FROM calls WHERE id=? AND grant_hash=?", (request_id, self.approved_sha)
            ).fetchone()
            if not row or row[0] != "reserved":
                raise PolicyDenied("RECEIPT_NOT_SETTLEABLE")
            db.execute(
                "UPDATE calls SET status=?,observed=?,basis=? WHERE id=?",
                (
                    "reconciling" if basis == "unknown" else "completed",
                    None if observed_usd is None else money(observed_usd),
                    basis,
                    request_id,
                ),
            )
            db.execute("COMMIT")
        finally:
            if db.in_transaction:
                db.execute("ROLLBACK")
            db.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="P7 preflight only; no requests or approval writes")
    parser.add_argument("--system", required=True, choices=["tradecase", "launchcase"])
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--upper-usd", default=None)
    args = parser.parse_args()
    policy = ValidationRunPolicy.from_env(args.system)
    result = policy.preflight(json.loads(args.request.read_text()), args.upper_usd, bool(os.getenv("OPENAI_API_KEY")))
    print(json.dumps(result))
    return 0 if result["status"] == "allowed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
