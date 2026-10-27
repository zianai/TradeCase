"""Single-writer file store with recoverable, journaled atomic revisions."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from tradecase.models import CaseInput, Manifest, SellerContext, TaskEvent
from tradecase.util import digest, json_bytes, no_symlinks, utc_now
from tradecase.validation import validate_artifact, validate_case

ARTIFACTS = {
    "input.json",
    "seller_context.json",
    "search_plan.md",
    "candidates.jsonl",
    "evidence.jsonl",
    "buyer_profile.json",
    "assessment.json",
    "compliance.json",
    "reply_draft.md",
    "next_actions.json",
    "report.md",
    "events.jsonl",
    "manifest.json",
}
TRANSITIONS = {
    "created": {"running", "needs_input", "failed", "cancelled"},
    "running": {"running", "needs_input", "needs_review", "completed", "failed", "cancelled"},
    "needs_input": {"running", "needs_input", "failed", "cancelled"},
    "needs_review": {"running", "needs_review", "completed", "failed", "cancelled"},
    "failed": {"running", "cancelled"},
    "completed": {"running"},
    "cancelled": {"running"},
}


def atomic_write(path: Path, data: bytes) -> None:
    no_symlinks(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def serialize(name, data) -> bytes:
    if name.endswith(".jsonl"):
        return b"".join(
            json.dumps(
                x.model_dump(mode="json") if hasattr(x, "model_dump") else x, sort_keys=True, ensure_ascii=False
            ).encode()
            + b"\n"
            for x in data
        )
    if name.endswith(".md"):
        return data.encode("utf-8")
    return json_bytes(data)


class CaseStore:
    def __init__(self, path: Path):
        self.path = Path(path).absolute()
        no_symlinks(self.path)

    @classmethod
    def create(cls, path: Path, inquiry: CaseInput | dict, seller: SellerContext | dict):
        store = cls(path)
        inquiry = CaseInput.model_validate(inquiry)
        seller = SellerContext.model_validate(seller)
        if store.path.exists():
            raise FileExistsError("Case directory already exists; use status/recover instead")
        store.path.mkdir(parents=True)
        now = utc_now()
        raw_input = json_bytes(inquiry)
        manifest = Manifest(
            case_id=inquiry.case_id, created_at=now, updated_at=now, input_hash=digest(raw_input), revision=0
        ).model_dump(mode="json")
        with store._lock():
            store._commit(manifest, {"input.json": raw_input, "seller_context.json": json_bytes(seller)}, "created", {})
        return store

    @contextmanager
    def _lock(self):
        lock = self.path / ".lock"
        no_symlinks(lock)
        with lock.open("a+b") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def _target(self, name):
        if name not in ARTIFACTS:
            raise ValueError(f"unknown artifact: {name}")
        path = self.path / name
        no_symlinks(path)
        return path

    def read(self, name):
        path = self._target(name)
        text = path.read_text("utf-8")
        if name.endswith(".jsonl"):
            if text and not text.endswith("\n"):
                raise ValueError(f"incomplete JSONL: {name}")
            return [json.loads(line) for line in text.splitlines() if line.strip()]
        return json.loads(text) if name.endswith(".json") else text

    def _check_pending(self):
        if (self.path / ".transaction.json").exists():
            raise ValueError("interrupted transaction; run tradecase recover first")

    def _commit(self, manifest, changes, event_type, detail):
        self._check_pending()
        manifest = dict(manifest)
        manifest["revision"] += 1
        manifest["updated_at"] = utc_now()
        index = dict(manifest["artifact_index"])
        for name, raw in changes.items():
            self._target(name)
            index[name] = digest(raw)
        manifest["artifact_index"] = index
        if "input.json" in changes:
            manifest["input_hash"] = digest(changes["input.json"])
        event = TaskEvent(
            case_id=manifest["case_id"],
            event_id="event-" + uuid4().hex,
            timestamp=manifest["updated_at"],
            event_type=event_type,
            stage=manifest["current_stage"],
            revision=manifest["revision"],
            detail=detail,
        )
        events = self.read("events.jsonl") if (self.path / "events.jsonl").exists() else []
        changes = dict(changes)
        changes["events.jsonl"] = serialize("events.jsonl", events + [event.model_dump(mode="json")])
        changes["manifest.json"] = json_bytes(Manifest.model_validate(manifest))
        # Journal includes after-images; recovery can replay these idempotently.
        journal = {"revision": manifest["revision"], "files": {k: v.decode("utf-8") for k, v in changes.items()}}
        for name in changes:
            path = self._target(name)
            if path.exists():
                atomic_write(self.path / ".history" / str(manifest["revision"] - 1) / name, path.read_bytes())
        atomic_write(self.path / ".transaction.json", json_bytes(journal))
        self._apply_journal(journal)

    def _apply_journal(self, journal):
        for name, content in journal["files"].items():
            self._target(name)
            data = (
                content
                if name.endswith(".md")
                else (
                    [json.loads(line) for line in content.splitlines() if line.strip()]
                    if name.endswith(".jsonl")
                    else json.loads(content)
                )
            )
            validate_artifact(name, data)
        # Manifest is the commit marker and is always written last.
        for name in sorted(journal["files"], key=lambda x: x == "manifest.json"):
            atomic_write(self._target(name), journal["files"][name].encode("utf-8"))
        (self.path / ".transaction.json").unlink()

    def recover(self):
        with self._lock():
            path = self.path / ".transaction.json"
            no_symlinks(path)
            if path.exists():
                self._apply_journal(json.loads(path.read_text("utf-8")))
            errors = validate_case(self.path)
            if errors:
                raise ValueError("; ".join(errors))
        return self.read("manifest.json")

    def write(self, name, data):
        if name in {"manifest.json", "events.jsonl", "input.json"}:
            raise ValueError("managed artifact; use store transitions or create a new Case")
        self._target(name)
        normalized = validate_artifact(name, data)
        with self._lock():
            self._check_pending()
            manifest = self.read("manifest.json")
            if manifest["state"] in {"completed", "cancelled"}:
                raise ValueError("final Case requires explicit reopen before edits")
            self._commit(manifest, {name: serialize(name, normalized)}, "artifact_updated", {"artifact": name})

    def transition(self, state, stage, *, error=None, blockers=None, detail=None):
        with self._lock():
            self._check_pending()
            manifest = self.read("manifest.json")
            if state not in TRANSITIONS[manifest["state"]]:
                raise ValueError(f"invalid transition: {manifest['state']} -> {state}")
            if state == "completed":
                errors = validate_case(self.path, strict=True)
                if errors:
                    raise ValueError("cannot complete invalid Case: " + "; ".join(errors))
                assessment = self.read("assessment.json")
                checks = self.read("compliance.json")["checks"]
                if assessment["decision"] == "needs_review" or any(
                    c["status"] not in {"pass", "not_applicable"} for c in checks
                ):
                    raise ValueError("unresolved assessment/compliance requires needs_review")
            manifest.update(state=state, current_stage=stage, error=error, blockers=blockers or [])
            self._commit(manifest, {}, state, detail or {})

    def record(self, event_type, detail):
        with self._lock():
            self._commit(self.read("manifest.json"), {}, event_type, detail)
