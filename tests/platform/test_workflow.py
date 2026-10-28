"""Actual StateGraph persistence/parallelism/interrupt/replay tests; no model API."""
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tradecase.platform.workflow import build_workflow, checkpoint_saver, invoke_workflow


class Host:
    def __init__(self, *, gaps=False, followup=False, decision="approved"):
        self.calls = []
        self.gaps, self.followup, self.decision = gaps, followup, decision
        self.parallel = set()
        self.all_started = asyncio.Event()

    async def step(self, name, state):
        self.calls.append(name)
        if name in {"identity_research", "company_profile_research", "buying_intent_research"}:
            self.parallel.add(name)
            if len(self.parallel) == 3:
                self.all_started.set()
            await asyncio.wait_for(self.all_started.wait(), 2)
            return {"research_refs": {name: "result-" + name},
                    "research_statuses": {name: "PARTIAL" if self.gaps else "COMPLETE"}}
        if name == "evidence_gate":
            return {"evidence_route": "gaps" if self.gaps else "sufficient", "followup_allowed": self.followup}
        if name == "prepare_approval":
            return {"approval_id": "approval-" + str(state.get("revision_round", 0))}
        if name == "validate_decision":
            assert set(state["decision"]) == {"approval_id"}
            assert state["decision"]["approval_id"] == state["approval_id"]
            return {"decision_valid": True, "decision": {"decision": self.decision}}
        if name == "update_case":
            return {"outcome": "READY_TO_FOLLOW_UP" if state["decision"]["decision"] == "approved" else "NEEDS_INPUT"}
        if name == "deterministic_quality_gate":
            return {"quality_passed": True}
        return {}


INITIAL = {"tenant_id": "org-a", "case_id": "case-a", "workflow_run_id": "workflow-a"}


def test_parallel_interrupt_resume_replay_durable(tmp_path):
    async def scenario():
        host = Host()
        url = "sqlite:///" + str(tmp_path / "checkpoints.sqlite")
        async with checkpoint_saver(url) as saver:
            graph = build_workflow(host, saver)
            first = await invoke_workflow(graph, INITIAL)
            assert first["__interrupt__"][0].value["approval_id"] == "approval-0"
            assert len(first["research_refs"]) == 3
            assert "persist_report" not in host.calls
        async with checkpoint_saver(url) as saver:
            graph = build_workflow(host, saver)
            result = await invoke_workflow(graph, INITIAL, {"approval_id": "approval-0"})
            assert result["outcome"] == "READY_TO_FOLLOW_UP"
            calls = host.calls[:]
            assert await invoke_workflow(graph, INITIAL) == result
            assert host.calls == calls
        assert host.calls.count("prepare_approval") == 1
        assert host.calls.count("parse_inquiry") == 1
    asyncio.run(scenario())


def test_partial_source_failure_bounded_followup(tmp_path):
    async def scenario():
        host = Host(gaps=True, followup=True)
        async with checkpoint_saver("sqlite:///" + str(tmp_path / "p.sqlite")) as saver:
            result = await invoke_workflow(build_workflow(host, saver), {**INITIAL, "max_rounds": 2})
            assert result["round"] == 2
            assert "budget exhausted" in result["review_reason"]
            assert host.calls.count("bounded_follow_up_research") == 2
            assert host.calls.count("merge_evidence") == 3
            assert all(v == "PARTIAL" for v in result["research_statuses"].values())
    asyncio.run(scenario())


@pytest.mark.parametrize("decision", ["rejected", "request_evidence"])
def test_reject_and_unavailable_evidence_dont_promote_case(tmp_path, decision):
    async def scenario():
        host = Host(gaps=True, decision=decision)
        async with checkpoint_saver("sqlite:///" + str(tmp_path / "p.sqlite")) as saver:
            graph = build_workflow(host, saver)
            await invoke_workflow(graph, INITIAL)
            result = await invoke_workflow(graph, INITIAL, {"approval_id": "approval-0"})
            assert result["outcome"] == "NEEDS_INPUT"
            assert "bounded_follow_up_research" not in host.calls
    asyncio.run(scenario())


def test_change_request_reinterrupts_then_hard_stops(tmp_path):
    async def scenario():
        host = Host(decision="request_changes")
        async with checkpoint_saver("sqlite:///" + str(tmp_path / "p.sqlite")) as saver:
            graph = build_workflow(host, saver)
            await invoke_workflow(graph, INITIAL)
            second = await invoke_workflow(graph, INITIAL, {"approval_id": "approval-0"})
            assert second["__interrupt__"][0].value["approval_id"] == "approval-1"
            third = await invoke_workflow(graph, INITIAL, {"approval_id": "approval-1"})
            assert third["outcome"] == "NEEDS_INPUT"
            assert host.calls.count("draft_response") == 2
    asyncio.run(scenario())


def test_checkpoint_cannot_be_reused_by_other_tenant_or_case(tmp_path):
    async def scenario():
        async with checkpoint_saver("sqlite:///" + str(tmp_path / "p.sqlite")) as saver:
            graph = build_workflow(Host(), saver)
            await invoke_workflow(graph, INITIAL)
            for changed in ({"tenant_id": "org-b"}, {"case_id": "case-b"}):
                with pytest.raises(PermissionError, match="identity_mismatch"):
                    await invoke_workflow(graph, {**INITIAL, **changed})
    asyncio.run(scenario())


def test_service_must_validate_resume(tmp_path):
    class RejectingHost(Host):
        async def step(self, name, state):
            if name == "validate_decision":
                return {"decision_valid": False}
            return await super().step(name, state)

    async def scenario():
        async with checkpoint_saver("sqlite:///" + str(tmp_path / "p.sqlite")) as saver:
            graph = build_workflow(RejectingHost(), saver)
            await invoke_workflow(graph, INITIAL)
            with pytest.raises(ValueError, match="not_validated"):
                await invoke_workflow(graph, INITIAL, {"approval_id": "approval-0"})
    asyncio.run(scenario())


def test_actual_process_restart_preserves_cursor(tmp_path):
    script = tmp_path / "process.py"
    script.write_text('''import asyncio, json, sys
from pathlib import Path
from tradecase.platform.workflow import build_workflow, checkpoint_saver, invoke_workflow
class Host:
 async def step(self, name, state):
  with open(sys.argv[2], 'a') as f: f.write(name + '\\n')
  if name == 'prepare_approval': return {'approval_id':'approval-1'}
  if name == 'evidence_gate': return {'evidence_route':'human'}
  if name == 'validate_decision': return {'decision_valid':True,'decision':{'decision':'approved'}}
  if name == 'update_case': return {'outcome':'READY_TO_FOLLOW_UP'}
  return {}
async def main():
 async with checkpoint_saver('sqlite:///' + sys.argv[1]) as saver:
  value = await invoke_workflow(build_workflow(Host(), saver),
   {'tenant_id':'t','case_id':'c','workflow_run_id':'w'},
   {'approval_id':'approval-1'} if sys.argv[3] == 'resume' else None)
  print(json.dumps({'waiting':bool(value.get('__interrupt__')), 'outcome':value.get('outcome')}))
asyncio.run(main())
''')
    db, calls = tmp_path / "p.sqlite", tmp_path / "calls.txt"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")}
    first = subprocess.run([sys.executable, str(script), str(db), str(calls), "start"],
                           capture_output=True, text=True, env=env, timeout=20)
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout)["waiting"]
    second = subprocess.run([sys.executable, str(script), str(db), str(calls), "resume"],
                            capture_output=True, text=True, env=env, timeout=20)
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout)["outcome"] == "READY_TO_FOLLOW_UP"
    stages = calls.read_text().splitlines()
    assert stages.count("parse_inquiry") == stages.count("prepare_approval") == 1


def test_reject_unbounded_host_state_and_unknown_backend(tmp_path):
    class BadHost(Host):
        async def step(self, name, state):
            return {"raw_html": "unsafe"}

    async def scenario():
        with pytest.raises(ValueError, match="unsupported_checkpoint"):
            async with checkpoint_saver("redis://localhost"):
                pass
        with pytest.raises(ValueError, match="durable_checkpoint"):
            async with checkpoint_saver("sqlite:///:memory:"):
                pass
        async with checkpoint_saver("sqlite:///" + str(tmp_path / "p.sqlite")) as saver:
            with pytest.raises(ValueError, match="invalid_state_fields"):
                await invoke_workflow(build_workflow(BadHost(), saver), INITIAL)
    asyncio.run(scenario())
