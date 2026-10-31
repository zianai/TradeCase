"""Local-only followup setup regression; no real key or network request."""
import asyncio
import json

import pytest

from ops.followup_live import execute, prepare
from tradecase.p7_policy import digest
from tradecase.platform.runtime import AgentTaskRequest


def test_frozen_followup_request_survives_json_roundtrip(tmp_path):
    root = (tmp_path / "synthetic-operator-scope").resolve()
    prepare(root)
    request = AgentTaskRequest.model_validate_json((root / "request.json").read_text())
    context = json.loads((root / "context.json").read_text())
    assert digest(request.model_dump()) == context["input_hash"]
    assert len(request.sources) == 2 and all(x.is_synthetic for x in request.sources)
    assert all(x.authority == "user_provided_unverified" for x in request.sources)
    assert (root / "grant.json").stat().st_mode & 0o077 == 0


def test_followup_changed_subject_stops_before_key_and_cannot_replay(tmp_path):
    root = (tmp_path / "synthetic-operator-scope").resolve()
    prepare(root)
    value = json.loads((root / "request.json").read_text())
    value["goal"] = "Changed after pinning"
    (root / "request.json").write_text(json.dumps(value))
    with pytest.raises(RuntimeError, match="Frozen request changed"):
        asyncio.run(execute(root, tmp_path / "missing-key"))
    assert not (root / "provider-request.json").exists()
    assert not (root / "reservations.sqlite").exists()
    with pytest.raises(FileExistsError):
        asyncio.run(execute(root, tmp_path / "missing-key"))
