"""Case-owned orchestration. Queue jobs lease this workflow; they do not schedule its nodes.

A checkpoint stores identifiers and bounded summaries, never inquiry/HTML/report bodies.
The host persists each node outcome idempotently before returning its reference. Database
facts remain authoritative; a checkpoint or resume payload is not an authorization.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Annotated, Any, AsyncIterator, Literal, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


def merge_map(left: dict | None, right: dict | None) -> dict:
    return {**(left or {}), **(right or {})}


class WorkflowState(TypedDict, total=False):
    tenant_id: str
    case_id: str
    workflow_run_id: str
    input_version: int
    round: int
    max_rounds: int
    revision_round: int
    revision_kind: str
    max_revisions: int
    research_refs: Annotated[dict[str, str], merge_map]
    research_statuses: Annotated[dict[str, str], merge_map]
    inquiry_ref: str
    entity_ref: str
    plan_ref: str
    evidence_ref: str
    assessment_ref: str
    risk_ref: str
    draft_ref: str
    report_ref: str
    approval_id: str
    approval_summary: dict
    evidence_route: Literal["sufficient", "gaps", "human"]
    followup_allowed: bool
    quality_passed: bool
    review_reason: str
    decision: dict
    decision_valid: bool
    outcome: str
    action_ref: str
    follow_up_ref: str
    visual_summary: dict
    visual_dispatch_count: int


class WorkflowHost(Protocol):
    async def step(self, name: str, state: dict) -> dict:
        """Execute/reuse a DB-backed node result; all writes require tenant scope.

        Research nodes return research_refs/statuses keyed by node name. The evidence
        gate returns evidence_route and followup_allowed only if a material, licensed,
        unqueried source remains within budget. prepare_approval is idempotent and
        releases Task leases with WAITING_HUMAN. validate_decision must reload the
        approval from DB, validate its artifact/Case versions and return decision_valid.
        approved_action_router rechecks policy and outbox records independently.
        """
        ...


def _bounded_update(value: dict) -> dict:
    if not isinstance(value, dict) or set(value) - set(WorkflowState.__annotations__):
        raise ValueError("workflow_host_invalid_state_fields")
    if len(json.dumps(value, ensure_ascii=False).encode()) > 16384:
        raise ValueError("workflow_state_payload_too_large_use_artifact_references")
    return value


def build_workflow(host: WorkflowHost, checkpointer: Any):
    """Build the only business control graph, without stacked node retries."""
    graph = StateGraph(WorkflowState)

    def node(name):
        async def execute(state):
            return _bounded_update(await host.step(name, dict(state)))
        return execute

    stages = (
        "parse_inquiry", "normalize_entities", "plan_research", "identity_research",
        "company_profile_research", "buying_intent_research", "merge_evidence", "resolve_conflicts",
        "evidence_gate", "lead_qualification", "compliance_checks", "draft_response",
        "deterministic_quality_gate", "prepare_approval", "validate_decision", "persist_report",
        "approved_action_router", "schedule_follow_up", "update_case",
    )
    for name in stages:
        graph.add_node(name, node(name))

    async def followup(state):
        # Enforce the outer hard bound even if a host erroneously says more research is possible.
        if not state.get("followup_allowed") or state.get("round", 0) >= state.get("max_rounds", 1):
            raise ValueError("workflow_followup_budget_exhausted")
        result = _bounded_update(await host.step("bounded_follow_up_research", dict(state)))
        return {**result, "round": state.get("round", 0) + 1}

    async def revision(state):
        if state.get("revision_round", 0) >= state.get("max_revisions", 1):
            raise ValueError("workflow_revision_budget_exhausted")
        return {"revision_round": state.get("revision_round", 0) + 1,
                "revision_kind": state.get("decision", {}).get("decision", "request_changes"),
                "decision": {}, "decision_valid": False}

    def human_review(state):
        return {"review_reason": state.get("review_reason") or "Evidence incomplete, conflicting, or budget exhausted"}

    def approval(state):
        # Deliberately no write before interrupt: this function re-enters on resume.
        answer = interrupt({
            "case_id": state["case_id"], "approval_id": state["approval_id"],
            "summary": state.get("approval_summary", {}), "review_reason": state.get("review_reason", ""),
        })
        if not isinstance(answer, dict):
            raise ValueError("decision_payload_must_be_object")
        return _bounded_update({"decision": answer, "decision_valid": False})

    graph.add_node("bounded_follow_up_research", followup)
    graph.add_node("bounded_revision", revision)
    graph.add_node("human_review", human_review)
    graph.add_node("approval_interrupt", approval)
    graph.add_edge(START, "parse_inquiry")
    graph.add_edge("parse_inquiry", "normalize_entities")
    if getattr(host, "visual_enabled", False):
        graph.add_node("visual_opportunity", node("visual_opportunity"))
        graph.add_node("visual_dispatch", node("visual_dispatch"))
        graph.add_edge("normalize_entities", "visual_opportunity")
        graph.add_edge("visual_opportunity", "visual_dispatch")
        graph.add_edge("visual_dispatch", "plan_research")
    else:
        graph.add_edge("normalize_entities", "plan_research")
    research = ["identity_research", "company_profile_research", "buying_intent_research"]
    for name in research:
        graph.add_edge("plan_research", name)
    graph.add_edge(research, "merge_evidence")
    graph.add_edge("merge_evidence", "resolve_conflicts")
    graph.add_edge("resolve_conflicts", "evidence_gate")

    def evidence_route(state):
        if state.get("evidence_route") == "sufficient":
            return "lead_qualification"
        if (state.get("evidence_route") == "gaps" and state.get("followup_allowed")
                and state.get("round", 0) < state.get("max_rounds", 1)):
            return "bounded_follow_up_research"
        return "human_review"

    graph.add_conditional_edges("evidence_gate", evidence_route,
                                ["lead_qualification", "bounded_follow_up_research", "human_review"])
    graph.add_edge("bounded_follow_up_research", "merge_evidence")
    graph.add_edge("human_review", "lead_qualification")
    graph.add_edge("lead_qualification", "compliance_checks")
    graph.add_edge("compliance_checks", "draft_response")
    graph.add_edge("draft_response", "deterministic_quality_gate")
    # Failed deterministic QA may still produce a reviewable artifact; service
    # policy must forbid approving/sending it until a validated revision exists.
    graph.add_edge("deterministic_quality_gate", "prepare_approval")
    graph.add_edge("prepare_approval", "approval_interrupt")
    graph.add_edge("approval_interrupt", "validate_decision")

    def decision_route(state):
        if not state.get("decision_valid"):
            raise ValueError("approval_not_validated_by_service")
        decision = state.get("decision", {}).get("decision")
        if decision == "request_evidence" and (
            not state.get("followup_allowed") or state.get("round", 0) >= state.get("max_rounds", 1)
        ):
            return "update_case"
        if decision in {"request_evidence", "request_changes"}:
            if state.get("revision_round", 0) < state.get("max_revisions", 1):
                return "bounded_revision"
            return "update_case"
        if decision in {"approved", "rejected"}:
            return "persist_report"
        raise ValueError("unsupported_approval_decision")

    def revision_route(state):
        if (state.get("revision_kind") == "request_evidence" and state.get("followup_allowed")
                and state.get("round", 0) < state.get("max_rounds", 1)):
            return "bounded_follow_up_research"
        return "draft_response"

    graph.add_conditional_edges("validate_decision", decision_route,
                                ["bounded_revision", "persist_report", "update_case"])
    graph.add_conditional_edges("bounded_revision", revision_route,
                                ["bounded_follow_up_research", "draft_response"])
    graph.add_edge("persist_report", "approved_action_router")
    graph.add_edge("approved_action_router", "schedule_follow_up")
    graph.add_edge("schedule_follow_up", "update_case")
    graph.add_edge("update_case", END)
    return graph.compile(checkpointer=checkpointer)


@asynccontextmanager
async def checkpoint_saver(url: str, *, setup: bool = False) -> AsyncIterator[Any]:
    """Durable SQLite for offline use; AsyncPostgresSaver for shared production.

    Production schema initialization is an explicit deployment operation. Never
    silently create checkpoint tables on each ordinary production request.
    """
    if url.startswith("postgresql"):
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        connection_string = url.replace("postgresql+psycopg://", "postgresql://", 1)
        async with AsyncPostgresSaver.from_conn_string(connection_string) as saver:
            if setup:
                await saver.setup()
            yield saver
    elif url.startswith("sqlite:///"):
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        path = url[len("sqlite:///"):]
        if not path or path == ":memory:":
            raise ValueError("durable_checkpoint_path_required")
        async with AsyncSqliteSaver.from_conn_string(path) as saver:
            await saver.setup()
            yield saver
    else:
        raise ValueError("unsupported_checkpoint_backend")


async def invoke_workflow(graph, initial: dict, decision: dict | None = None) -> dict:
    """Resume a stable tenant-bound workflow; duplicate jobs don't reset the graph.

    Caller must hold a DB lease for workflow_run_id throughout invocation. This
    function is not a second lock manager and cannot make external writes safe.
    """
    required = {"tenant_id", "case_id", "workflow_run_id"}
    if not required <= initial.keys() or any(not initial[key] for key in required):
        raise ValueError("workflow_identity_required")
    for name, default in (("max_rounds", 1), ("max_revisions", 1)):
        if type(initial.get(name, default)) is not int or not 0 <= initial.get(name, default) <= 3:
            raise ValueError("workflow_round_limit_invalid")
    config = {"configurable": {"thread_id": initial["workflow_run_id"]}, "recursion_limit": 100}
    snapshot = await graph.aget_state(config)
    if snapshot.values:
        if any(snapshot.values.get(key) != initial[key] for key in required):
            raise PermissionError("workflow_identity_mismatch")
        if not snapshot.next:
            return dict(snapshot.values)
        value = Command(resume=decision) if decision is not None else None
    else:
        if decision is not None:
            raise ValueError("cannot_resume_unknown_workflow")
        value = _bounded_update({"round": 0, "max_rounds": 1, "revision_round": 0,
                                 "max_revisions": 1, **initial})
    return await graph.ainvoke(value, config)
