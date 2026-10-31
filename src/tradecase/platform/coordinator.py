"""One DB-leased coordinator enters the Case graph; queues only wake it."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from datetime import datetime, timedelta

from sqlalchemy import or_, select, update

from tradecase.platform import db as m
from tradecase.platform.kernel import BusinessKernel
from tradecase.platform.knowledge import KnowledgeService
from tradecase.platform.review_inputs import ReviewInputsService
from tradecase.platform.runtime import (
    AgentBudget,
    AgentTaskRequest,
    AgentTaskResult,
    FakeAgentRunner,
    OpenAIAgentRunner,
    ResearchClaim,
    ResearchResult,
    SourceSnapshot,
    ToolDescriptor,
    ToolRegistry,
)
from tradecase.platform.services import ServiceError, fingerprint
from tradecase.platform.tasks import TaskManager
from tradecase.platform.workflow import build_workflow, checkpoint_saver, invoke_workflow
from tradecase.reporting import safe_md
from tradecase.upstream import claim_risk

RESEARCH = {"identity_research", "company_profile_research", "buying_intent_research", "bounded_follow_up_research"}


class PlatformWorkflowHost:
    def __init__(self, service, runner=None):
        self.service = service
        from tradecase.visual.settings import VisualSettings
        self.visual_enabled = VisualSettings().enabled
        self.db = service.db
        self.kernel = BusinessKernel(service)
        self.tasks = TaskManager(self.db)
        self.active_leases = {}
        registry = ToolRegistry()
        self.registry = registry
        knowledge = KnowledgeService(service)

        async def search_knowledge(arguments, request):
            items = knowledge.search(request.tenant_id, arguments.get("query", ""), limit=3)
            snapshots = [
                SourceSnapshot(
                    source_id="knowledge-" + item["id"] + "-v" + str(item["version"]),
                    url="knowledge://" + request.tenant_id + "/" + item["id"] + "/" + str(item["version"]),
                    source_type="user_provided_unverified",
                    authority="user_provided_unverified",
                    title=item["title"],
                    captured_at=item["created_at"],
                    text=item["content"][:64000],
                    license_status="permitted",
                    document_version=item["version"],
                    valid_until=item["valid_until"],
                    document_hash=item["content_hash"],
                )
                for item in items
            ]
            return {
                "status": "fetched" if snapshots else "NO_MATCH",
                "sources": [x.model_dump() for x in snapshots],
                "authority": "user_provided_unverified",
            }

        registry.register(
            ToolDescriptor(
                name="search_internal_knowledge",
                description=(
                    "Search authorized current tenant knowledge. All documents are user-provided unverified background."
                ),
                available=True,
                license_status="permitted",
                unavailable_reason="",
            ),
            search_knowledge,
        )
        registry.register_public_reader(
            enabled=service.settings.public_fetch_enabled, permitted=service.settings.public_fetch_enabled
        )
        from tradecase.platform.source_cache import SourceCacheService

        SourceCacheService(service).wrap(registry)
        self.runner = runner or (
            OpenAIAgentRunner(
                registry,
                skills_root=service.settings.skills_root,
                live_enabled=service.settings.live_model_enabled,
                usd_per_token_upper_bound=service.settings.usd_per_token_upper_bound,
            )
            if service.settings.runtime == "openai"
            else FakeAgentRunner()
        )

    def assert_workflow_lease(self, state):
        token = self.active_leases.get(state["workflow_run_id"])
        if token is None:
            raise ServiceError("Workflow invocation requires its coordinator lease")
        with self.db.session() as session:
            row = self.service.scoped(session, m.WorkflowRun, state["tenant_id"], state["workflow_run_id"])
            if row.lease_token != token or row.lease_until is None or row.lease_until <= m.utcnow():
                raise ServiceError("Workflow lease lost")

    async def step(self, name, state):
        self.assert_workflow_lease(state)
        tenant, case_id = state["tenant_id"], state["case_id"]
        self.service.get(tenant, case_id)
        fp = fingerprint(
            [
                state["workflow_run_id"],
                name,
                state.get("round", 0),
                state.get("revision_round", 0),
                state.get("input_version", 1),
            ]
        )
        task = self.tasks.ensure(tenant, case_id, name, fp, payload={"workflow_run_id": state["workflow_run_id"]})
        if task.status == "SUCCEEDED" and name not in {"validate_decision", "prepare_approval"}:
            return task.result or {}
        if name == "prepare_approval" and task.status == "WAITING_HUMAN":
            return task.result or {}
        if name == "validate_decision" and task.status == "SUCCEEDED":
            self.resolve_review_tasks(tenant, case_id, state["approval_id"])
            return task.result or {}
        lease = self.tasks.claim(
            tenant,
            task.id,
            "workflow-" + state["workflow_run_id"],
            lease_seconds=max(180, self.service.settings.max_case_seconds + 30),
        )
        if lease is None:
            raise ServiceError("Task is not claimable; wait for lease/retry policy")
        try:
            if name in RESEARCH:
                result = await self._research(name, state, lease)
            else:
                result = self._deterministic(name, state)
            if name == "validate_decision":
                self.resolve_review_tasks(tenant, case_id, state["approval_id"])
            self.assert_workflow_lease(state)
            if name == "prepare_approval":
                self.tasks.wait_human(lease, result=result)
            else:
                self.tasks.complete(lease, result)
            return result
        except BaseException as exc:
            with suppress(Exception):
                self.tasks.fail(
                    lease,
                    type(exc).__name__,
                    retryable=isinstance(exc, (OSError, TimeoutError, asyncio.CancelledError)),
                )
            with self.db.session() as session:
                session.execute(
                    update(m.AgentRun)
                    .where(
                        m.AgentRun.tenant_id == tenant,
                        m.AgentRun.attempt_id == lease.attempt_id,
                        m.AgentRun.status == "RUNNING",
                    )
                    .values(
                        status="CANCELLED" if isinstance(exc, asyncio.CancelledError) else "FAILED",
                        finished_at=m.utcnow(),
                        error_class=type(exc).__name__,
                    )
                )
            raise

    def resolve_review_tasks(self, tenant, case_id, approval_id):
        with self.db.session() as session:
            pending = list(
                session.scalars(
                    select(m.Task).where(
                        m.Task.tenant_id == tenant,
                        m.Task.case_id == case_id,
                        m.Task.task_type == "prepare_approval",
                        m.Task.status == "WAITING_HUMAN",
                    )
                )
            )
        for task in pending:
            bound_id = (task.result or {}).get("approval_id")
            if bound_id == approval_id:
                self.tasks.resolve_human(tenant, task.id)
            elif bound_id:
                with self.db.session() as session:
                    approval = self.service.scoped(session, m.Approval, tenant, bound_id)
                    invalid = approval.status == "INVALIDATED"
                if invalid:
                    self.tasks.cancel(tenant, task.id)

    async def _research(self, name, state, lease):
        tenant, case_id = state["tenant_id"], state["case_id"]
        case = self.service.get(tenant, case_id)
        if case["data"].get("review_inputs_ref"):
            bundle = ReviewInputsService(self.service).bundle(tenant, case_id)
            if bundle["assessment"]["decision"] != "needs_review":
                return {"research_refs": {}, "research_statuses": {name: "COMPLETE"}}
        run_id = m.uid()
        settings = self.service.settings
        with self.db.session() as s:
            self.service.lock_case(s, tenant, case_id)
            # Reserve the per-run ceiling under the Case lock before parallel calls.
            # A crashed attempt retains its reservation until billing is reconciled.
            previous = list(
                s.scalars(select(m.AgentRun).where(m.AgentRun.tenant_id == tenant, m.AgentRun.case_id == case_id))
            )
            remaining = max(0, settings.max_case_cost_usd - sum(item.cost for item in previous))
            allocated = min(remaining, settings.max_case_cost_usd / (3 + settings.max_research_rounds))
            s.add(
                m.AgentRun(
                    id=run_id,
                    tenant_id=tenant,
                    case_id=case_id,
                    task_id=lease.task_id,
                    attempt_id=lease.attempt_id,
                    provider="fake" if case["synthetic"] else self.service.settings.runtime,
                    model=self.service.settings.model,
                    cost=allocated if not case["synthetic"] and settings.runtime == "openai" else 0,
                    data={"workflow_run_id": state["workflow_run_id"], "cost_reserved": allocated},
                )
            )
        runner = FakeAgentRunner(self._fixture_research(tenant, case_id)) if case["synthetic"] else self.runner
        request = AgentTaskRequest(
            tenant_id=tenant,
            case_id=case_id,
            task_id=lease.task_id,
            agent_run_id=run_id,
            task_type=name,
            goal="Collect cited " + name.replace("_", " ") + "; report unavailable sources and ambiguity.",
            context={
                "inquiry": case["inquiry"]["buyer_message"][:12000],
                "website_hint": case["inquiry"].get("buyer_website_hint"),
            },
            input_refs=[case["inquiry_id"]],
            allowed_tools=["search_internal_knowledge"]
            + (["fetch_page"] if settings.public_fetch_enabled and settings.research_domains else []),
            allowed_domains=list(settings.research_domains),
            budget=AgentBudget(
                max_turns=settings.max_model_turns,
                max_tool_calls=settings.max_tool_calls,
                max_total_tokens=settings.max_research_tokens,
                max_cost_usd=allocated,
                max_wall_seconds=min(90, settings.max_case_seconds),
            ),
            model=self.service.settings.model or None,
        )
        result = await runner.run(request)
        self.assert_workflow_lease(state)
        with self.db.session() as s:
            run = self.service.scoped(s, m.AgentRun, tenant, run_id)
            run.status = (
                "FAILED"
                if result.error_class and result.error_class not in {"BudgetExceeded", "TimeoutError"}
                else result.status
            )
            run.finished_at = m.utcnow()
            run.provider = result.provider
            run.model = result.model or self.service.settings.model
            run.stop_reason = result.stop_reason[:100]
            run.error_class = result.error_class
            run.token_usage = result.token_usage
            run.cost = result.cost_usd
            run.tool_events = [x.model_dump(mode="json") for x in result.tool_events]
            # Result blobs are immutable and outside checkpoints.
            obj = self.service.storage.put(result.model_dump_json().encode())
            run.artifact_refs = [obj.key]
            run.data = {
                **run.data,
                "result_ref": obj.key,
                "synthetic": result.synthetic,
                "cost_is_estimate": result.cost_is_estimate,
                "provenance": result.provenance,
            }
            self.service.event(
                s,
                tenant,
                case_id,
                "agent.finished",
                {"status": run.status, "synthetic": result.synthetic},
                task_id=lease.task_id,
                agent_run_id=run_id,
            )
        if result.error_class and result.error_class not in {"BudgetExceeded", "TimeoutError"}:
            raise ServiceError("Agent technical failure: " + result.error_class)
        return {
            "research_refs": {name: run_id},
            "research_statuses": {name: result.status},
        }

    def _fixture_research(self, tenant, case_id):
        """Replay genuine fixture observations; no promotion of an empty fake result."""
        store = self.kernel.materialize(tenant, case_id)
        rows = store.read("evidence.jsonl")
        sources, claims = [], []
        for row in rows:
            snapshot = row.get("local_snapshot_ref")
            text = (store.path / snapshot).read_text() if snapshot else row.get("excerpt", "")
            source = SourceSnapshot(
                source_id=row["evidence_id"],
                url=row.get("source_url") or "",
                source_type=row["source_type"],
                title=row.get("source_title") or "",
                captured_at=row["captured_at"],
                text=text,
                is_synthetic=True,
                license_status="permitted",
            )
            sources.append(source)
            factual = row["assertion_status"] == "supported" and row.get("excerpt") and row["excerpt"] in text
            claims.append(
                ResearchClaim(
                    claim_id=row["evidence_id"],
                    entity_id=row.get("entity_candidate_id") or "inquiry",
                    attribute="fixture_observation",
                    text=row["claim"],
                    classification="FACT" if factual else "UNKNOWN",
                    source_ids=[source.source_id],
                    excerpt=row.get("excerpt") or "",
                )
            )
        unresolved = store.read("buyer_profile.json").get("unresolved_items", [])
        if any(row["assertion_status"] != "supported" for row in rows):
            unresolved = [*unresolved, "Fixture contains unverified or contradicted observations"]
        return ResearchResult(
            status="PARTIAL" if unresolved else "COMPLETE",
            claims=claims,
            sources=sources,
            unresolved_questions=unresolved[:50],
            stop_reason="synthetic_fixture_replay",
        )

    def current_report(self, tenant, case_id):
        """Render existing business findings with the exact current DB draft version."""
        report = self.kernel.compute(tenant, case_id, "persist_report")
        with self.db.session() as session:
            version = self.service.current_artifact(session, tenant, case_id, "draft")
            draft = json.loads(self.service.storage.get(version.storage_ref))
        head, separator, tail = report.partition("## Reply draft")
        if separator:
            _, pending, remaining = tail.partition("## Pending confirmations")
            tail = pending + remaining
        else:
            head, tail = report, ""
        current = (
            "## Reply draft\n\nSubject: "
            + safe_md(draft.get("subject", ""))
            + "\n\n"
            + safe_md(draft.get("body_text", ""))
            + "\n\nArtifact version: "
            + version.id
            + "\n\nArtifact SHA256: "
            + version.content_hash
            + "\n\n"
        )
        visual = ""
        if self.visual_enabled:
            try:
                from tradecase.visual.service import VisualService
                summary = VisualService(self.service).summary_for_case(tenant, case_id)
                if summary["tasks"]:
                    visual = "\n\n## Visual Proposal\n\n"
                    for item in summary["tasks"]:
                        visual += safe_md(item["id"] + ": " + item["status"]) + "\n\n"
                    visual += "Generated visuals are communication artifacts, not factual evidence. Only current human-approved assets may be delivered.\n"
            except Exception:
                pass
        return head + current + tail + visual

    def _deterministic(self, name, state):
        tenant, case_id = state["tenant_id"], state["case_id"]
        service = self.service
        if name in {"visual_opportunity", "visual_dispatch"}:
            # Optional branch is read-only and cannot make Case research depend on an engine.
            try:
                from tradecase.visual.service import VisualService
                summary = VisualService(service).summary_for_case(tenant, case_id)
                if name == "visual_opportunity":
                    return {"visual_summary": {"count": len(summary["suggestions"]),
                            "status": "suggested" if summary["suggestions"] else "not_recommended"}}
                return {"visual_dispatch_count": sum(t["status"] == "queued" for t in summary["tasks"])}
            except Exception:
                return {"visual_summary": {"status": "unavailable", "count": 0}} if name == "visual_opportunity" else {"visual_dispatch_count": 0}
        if name == "parse_inquiry":
            store = self.kernel.materialize(tenant, case_id)
            return {"inquiry_ref": service.get(tenant, case_id)["inquiry_id"]}
        store = self.kernel.materialize(tenant, case_id)
        if name == "normalize_entities":
            with self.db.session() as s:
                case = service.lock_case(s, tenant, case_id)
                # Do not merge by name. Explicit candidate country/domain boundaries survive.
                candidates = store.read("candidates.jsonl")
                profile = store.read("buyer_profile.json")
                if profile.get("selected_candidate_id"):
                    row = next((r for r in candidates if r["candidate_id"] == profile["selected_candidate_id"]), None)
                    if row:
                        entity = s.scalar(
                            select(m.BuyerEntity).where(
                                m.BuyerEntity.tenant_id == tenant,
                                m.BuyerEntity.legal_name == row["name"],
                                m.BuyerEntity.country == row.get("country"),
                                m.BuyerEntity.domain == row.get("domain"),
                                m.BuyerEntity.registry_id == row.get("registry_id"),
                            )
                        )
                        if entity is None:
                            entity = m.BuyerEntity(
                                id=m.uid(),
                                tenant_id=tenant,
                                legal_name=row["name"],
                                country=row.get("country"),
                                domain=row.get("domain"),
                                registry_id=row.get("registry_id"),
                                confidence=row["identity_status"].upper(),
                                data={"candidate": row, "synthetic": case.data.get("synthetic")},
                            )
                            s.add(entity)
                            s.flush()
                        case.buyer_entity_id = entity.id
                case.data = {**case.data, "candidates": candidates, "profile": profile}
                return {"entity_ref": case.buyer_entity_id or case.id}
        if name == "plan_research":
            return {"plan_ref": state["workflow_run_id"], "followup_allowed": False}
        if name == "merge_evidence":
            with self.db.session() as s:
                case = service.lock_case(s, tenant, case_id)
                rows = store.read("evidence.jsonl")
                for item in rows:
                    snapshot = item.get("local_snapshot_ref")
                    raw = (
                        (store.path / snapshot).read_bytes()
                        if snapshot and (store.path / snapshot).exists()
                        else (item.get("excerpt") or "").encode()
                    )
                    obj = service.storage.put(raw)
                    sf = fingerprint([item.get("source_url"), obj.sha256])
                    source = s.scalar(
                        select(m.Source).where(
                            m.Source.tenant_id == tenant, m.Source.case_id == case_id, m.Source.fingerprint == sf
                        )
                    )
                    if source is None:
                        source = m.Source(
                            id=m.uid(),
                            tenant_id=tenant,
                            case_id=case_id,
                            fingerprint=sf,
                            url=item.get("source_url"),
                            source_type=item["source_type"],
                            title=item.get("source_title") or "",
                            captured_at=datetime.fromisoformat(item["captured_at"].replace("Z", "+00:00")),
                            license_status="SYNTHETIC" if item["is_synthetic"] else "UNKNOWN",
                            status="FETCHED",
                            snapshot_ref=obj.key,
                            snapshot_hash=obj.sha256,
                            data={"excerpt": item.get("excerpt"), "synthetic": item["is_synthetic"]},
                        )
                        s.add(source)
                        s.flush()
                    cf = fingerprint(
                        [
                            item.get("entity_candidate_id") or "inquiry",
                            "fixture_observation",
                            item["claim"],
                            "FACT" if item["assertion_status"] == "supported" else "UNKNOWN",
                        ]
                    )
                    claim = s.scalar(
                        select(m.Claim).where(
                            m.Claim.tenant_id == tenant, m.Claim.case_id == case_id, m.Claim.fingerprint == cf
                        )
                    )
                    if claim is None:
                        claim = m.Claim(
                            id=m.uid(),
                            tenant_id=tenant,
                            case_id=case_id,
                            fingerprint=cf,
                            subject=item.get("entity_candidate_id") or "inquiry",
                            predicate="fixture_observation",
                            statement=item["claim"],
                            classification="FACT" if item["assertion_status"] == "supported" else "UNKNOWN",
                            status=item["assertion_status"].upper(),
                            data={"legacy_evidence_id": item["evidence_id"], "synthetic": item["is_synthetic"]},
                        )
                        s.add(claim)
                        s.flush()
                        s.add(
                            m.ClaimEvidenceLink(
                                tenant_id=tenant,
                                case_id=case_id,
                                claim_id=claim.id,
                                source_id=source.id,
                                relation="refutes" if item["assertion_status"] == "contradicted" else "supports",
                                excerpt=item.get("excerpt") or "",
                                locator=item.get("locator"),
                            )
                        )
                # Adapter results are independent cited evidence; they never rewrite legacy scores.
                for run_id in state.get("research_refs", {}).values():
                    run = service.scoped(s, m.AgentRun, tenant, run_id)
                    if run.case_id != case_id:
                        raise ServiceError("Research result belongs to another Case")
                    result = AgentTaskResult.model_validate_json(
                        service.storage.get(run.data["result_ref"])
                    ).model_dump()
                    for c in result["claims"]:
                        if not c["source_ids"]:
                            cf = fingerprint([c["entity_id"], c["attribute"], c["text"], c["classification"]])
                            exists = s.scalar(
                                select(m.Claim.id).where(
                                    m.Claim.tenant_id == tenant, m.Claim.case_id == case_id, m.Claim.fingerprint == cf
                                )
                            )
                            if not exists:
                                s.add(
                                    m.Claim(
                                        tenant_id=tenant,
                                        case_id=case_id,
                                        fingerprint=cf,
                                        subject=c["entity_id"],
                                        predicate=c["attribute"],
                                        statement=c["text"],
                                        classification=c["classification"],
                                        status="UNVERIFIED",
                                        data={},
                                    )
                                )
                    for src in result["sources"]:
                        if src["is_synthetic"] and not case.data.get("synthetic"):
                            raise ServiceError("Synthetic source in live Case")
                        sf = fingerprint([src["url"], src["sha256"]])
                        source = s.scalar(
                            select(m.Source).where(
                                m.Source.tenant_id == tenant, m.Source.case_id == case_id, m.Source.fingerprint == sf
                            )
                        )
                        if source is None:
                            obj = service.storage.put(src["text"].encode())
                            source = m.Source(
                                id=m.uid(),
                                tenant_id=tenant,
                                case_id=case_id,
                                fingerprint=sf,
                                url=src["url"],
                                title=src["title"],
                                source_type=src["source_type"],
                                status=src["status"].upper(),
                                license_status=src["license_status"],
                                snapshot_ref=obj.key,
                                snapshot_hash=obj.sha256,
                                captured_at=datetime.fromisoformat(src["captured_at"].replace("Z", "+00:00")),
                                data={
                                    "gap_reason": src["gap_reason"],
                                    "synthetic": src["is_synthetic"],
                                    "authority": src["authority"],
                                    "document_version": src["document_version"],
                                    "valid_until": src["valid_until"],
                                    "document_hash": src["document_hash"],
                                },
                            )
                            s.add(source)
                            s.flush()
                        for c in result["claims"]:
                            if src["source_id"] not in c["source_ids"]:
                                continue
                            cf = fingerprint([c["entity_id"], c["attribute"], c["text"], c["classification"]])
                            claim = s.scalar(
                                select(m.Claim).where(
                                    m.Claim.tenant_id == tenant, m.Claim.case_id == case_id, m.Claim.fingerprint == cf
                                )
                            )
                            if claim is None:
                                claim = m.Claim(
                                    id=m.uid(),
                                    tenant_id=tenant,
                                    case_id=case_id,
                                    fingerprint=cf,
                                    subject=c["entity_id"],
                                    predicate=c["attribute"],
                                    statement=c["text"],
                                    classification=c["classification"],
                                    status="UNVERIFIED",
                                    data={},
                                )
                                s.add(claim)
                                s.flush()
                            linked = s.scalar(
                                select(m.ClaimEvidenceLink.id).where(
                                    m.ClaimEvidenceLink.tenant_id == tenant,
                                    m.ClaimEvidenceLink.claim_id == claim.id,
                                    m.ClaimEvidenceLink.source_id == source.id,
                                )
                            )
                            if not linked:
                                s.add(
                                    m.ClaimEvidenceLink(
                                        tenant_id=tenant,
                                        case_id=case_id,
                                        claim_id=claim.id,
                                        source_id=source.id,
                                        excerpt=c["excerpt"],
                                    )
                                )
                return {"evidence_ref": case_id}
        if name == "resolve_conflicts":
            candidates = store.read("candidates.jsonl")
            profile = store.read("buyer_profile.json")
            conflicts = list(profile.get("unresolved_items", []))
            if any(c["identity_status"] == "ambiguous" for c in candidates):
                conflicts.append("ENTITY_AMBIGUOUS")
            with self.db.session() as s:
                case = service.lock_case(s, tenant, case_id)
                for run_id in state.get("research_refs", {}).values():
                    run = service.scoped(s, m.AgentRun, tenant, run_id)
                    result = AgentTaskResult.model_validate_json(service.storage.get(run.data["result_ref"]))
                    conflicts.extend(result.conflicts)
                selected_claim_ids = None
                if case.data.get("review_inputs_ref"):
                    bundle = ReviewInputsService(service).bundle(tenant, case_id)
                    selected_claim_ids = {row["claim_id"] for row in bundle["request"]["evidence_bindings"]}
                grouped = {}
                for claim in s.scalars(select(m.Claim).where(m.Claim.tenant_id == tenant, m.Claim.case_id == case_id)):
                    if selected_claim_ids is not None and claim.id not in selected_claim_ids:
                        continue
                    if claim.predicate in {"country", "domain", "registration", "registry_id", "legal_name"}:
                        grouped.setdefault((claim.subject, claim.predicate), set()).add(
                            claim.statement.strip().casefold()
                        )
                if any(len(values) > 1 for values in grouped.values()):
                    conflicts.append("SOURCE_CONFLICT: different observations for one entity attribute")
                conflicts = list(dict.fromkeys(conflicts))
                case.data = {**case.data, "conflicts": conflicts}
            return {"review_reason": "; ".join(conflicts)[:1000]}
        if name == "evidence_gate":
            case = service.get(tenant, case_id)
            statuses = state.get("research_statuses", {})
            assessment = store.read("assessment.json")
            complete = (
                bool(statuses)
                and all(value == "COMPLETE" for value in statuses.values())
                and not case["conflicts"]
                and assessment["decision"] != "needs_review"
            )
            with self.db.session() as s:
                row = service.lock_case(s, tenant, case_id)
                row.data = {**row.data, "research_status": "COMPLETE" if complete else "PARTIAL"}
            return {
                "evidence_route": "sufficient" if complete else "human",
                "followup_allowed": False,
                "review_reason": ""
                if complete
                else "Evidence remains partial; unavailable sources require human review.",
            }
        if name == "lead_qualification":
            result = self.kernel.compute(tenant, case_id, name)
            if not isinstance(result, dict):
                result = store.read("assessment.json")
            with self.db.session() as s:
                case = service.lock_case(s, tenant, case_id)
                exists = s.scalar(
                    select(m.LeadAssessment).where(
                        m.LeadAssessment.tenant_id == tenant,
                        m.LeadAssessment.case_id == case_id,
                        m.LeadAssessment.version == case.version,
                    )
                )
                if not exists:
                    s.add(
                        m.LeadAssessment(
                            tenant_id=tenant,
                            case_id=case_id,
                            version=case.version,
                            dimensions=result.get("signals", {}),
                            data=result,
                        )
                    )
                case.data = {**case.data, "assessment": result}
                case.priority = result.get("score") or 0
            return {"assessment_ref": case_id}
        if name == "compliance_checks":
            result = self.kernel.compute(tenant, case_id, name)
            with self.db.session() as s:
                case = service.lock_case(s, tenant, case_id)
                for previous in s.scalars(
                    select(m.RiskFinding).where(m.RiskFinding.tenant_id == tenant, m.RiskFinding.case_id == case_id)
                ):
                    previous.data = {**previous.data, "active": False}
                for risk in result["checks"]:
                    row = s.scalar(
                        select(m.RiskFinding).where(
                            m.RiskFinding.tenant_id == tenant,
                            m.RiskFinding.case_id == case_id,
                            m.RiskFinding.rule_id == risk["rule_id"],
                            m.RiskFinding.data["case_version"].as_integer() == case.version,
                        )
                    )
                    if not row:
                        s.add(
                            m.RiskFinding(
                                tenant_id=tenant,
                                case_id=case_id,
                                category=risk["check_type"],
                                severity=risk["severity"],
                                jurisdiction=risk.get("jurisdiction"),
                                rule_id=risk["rule_id"],
                                rule_version=risk["rule_version"],
                                status=risk["status"],
                                requires_review=risk["status"] not in {"pass", "not_applicable"},
                                evidence_refs=risk["evidence_ids"],
                                data={**risk, "case_version": case.version, "active": True},
                            )
                        )
                    else:
                        row.status = risk["status"]
                        row.severity = risk["severity"]
                        row.rule_version = risk["rule_version"]
                        row.requires_review = risk["status"] not in {"pass", "not_applicable"}
                        row.evidence_refs = risk["evidence_ids"]
                        row.data = {**risk, "case_version": case.version, "active": True}
                case.data = {
                    **case.data,
                    "unresolved_risks": any(c["status"] not in {"pass", "not_applicable"} for c in result["checks"]),
                }
            return {"risk_ref": case_id}
        if name == "draft_response":
            review = self.kernel.compute(tenant, case_id, name)
            with self.db.session() as s:
                case = service.lock_case(s, tenant, case_id)
                # A persisted decision may be resumed after a delivery began.
                # Fence the authoritative write as well as the decision endpoint.
                service.ensure_no_outbound_inflight(s, case)
                revision_key = fingerprint(
                    [state["workflow_run_id"], state.get("input_version", 1), state.get("revision_round", 0)]
                )
                applied = case.data.get("applied_draft_revisions", [])
                if state.get("revision_round", 0) and revision_key not in applied:
                    case.version += 1
                    case.data = {**case.data, "applied_draft_revisions": [*applied, revision_key]}
                    s.execute(
                        update(m.Approval)
                        .where(
                            m.Approval.tenant_id == tenant,
                            m.Approval.case_id == case_id,
                            m.Approval.status.in_(["PENDING", "APPROVED"]),
                        )
                        .values(status="INVALIDATED")
                    )
                v = service.save_artifact(s, case, "draft", review["message"], {"qa": review})
                return {"draft_ref": v.id}
        if name == "deterministic_quality_gate":
            with self.db.session() as s:
                case = service.lock_case(s, tenant, case_id)
                version = service.current_artifact(s, tenant, case_id, "draft")
                draft = json.loads(service.storage.get(version.storage_ref))
                review, blocks, actions = [], [], []
                claim_risk(draft, review, blocks, actions)
                quality = not blocks and not review
                case.data = {**case.data, "quality_passed": quality}
                # A report is visible before the human decision, then final decision is appended later.
                report = self.current_report(tenant, case_id)
                service.save_artifact(s, case, "report", report)
                return {"quality_passed": quality}
        if name == "prepare_approval":
            with self.db.session() as s:
                case = service.lock_case(s, tenant, case_id)
                service.transition(s, case, "NEEDS_REVIEW")
                approval = service.prepare_approval(s, case)
                workflow = service.scoped(s, m.WorkflowRun, tenant, state["workflow_run_id"])
                workflow.data = {**workflow.data, "current_approval_id": approval.id}
                return {
                    "approval_id": approval.id,
                    "approval_summary": {
                        "artifact_hash": approval.artifact_hash,
                        "case_version": approval.case_version,
                        "scope": approval.action_scope,
                    },
                }
        if name == "validate_decision":
            with self.db.session() as s:
                case = service.lock_case(s, tenant, case_id)
                identity = state.get("decision", {}).get("approval_id")
                if identity != state.get("approval_id"):
                    raise ServiceError("Decision does not match workflow approval")
                approval = service.scoped(s, m.Approval, tenant, identity)
                service.validate_approval(s, case, approval, "draft_review")
                if not approval.decision or approval.status not in {"APPROVED", "REJECTED", "CHANGES_REQUESTED"}:
                    raise ServiceError("Decision has not been persisted by a reviewer")
                return {"decision_valid": True, "decision": {"decision": approval.decision, "approval_id": identity}}
        if name == "persist_report":
            text = self.current_report(tenant, case_id) + "\n\nHuman decision: " + state["decision"]["decision"] + "\n"
            with self.db.session() as s:
                case = service.lock_case(s, tenant, case_id)
                v = service.save_artifact(s, case, "report", text)
                return {"report_ref": v.id}
        if name == "approved_action_router":
            # Draft review authorizes human use only. Separate explicit send approval + API action required.
            return {"outcome": "manual_follow_up" if state["decision"]["decision"] == "approved" else "rejected"}
        if name == "schedule_follow_up":
            with self.db.session() as s:
                case = service.lock_case(s, tenant, case_id)
                approval = service.scoped(s, m.Approval, tenant, state["approval_id"])
                action = (
                    "Review evidence gaps and manually follow up with the buyer"
                    if state["decision"]["decision"] == "approved"
                    else "Revise inquiry response after rejected review"
                )
                row = service.ensure_followup(
                    s, case, action, state["workflow_run_id"] + ":followup", approval.reviewer_id
                )
                return {"follow_up_ref": row.id}
        if name == "update_case":
            decision = state.get("decision", {}).get("decision")
            with self.db.session() as s:
                case = service.lock_case(s, tenant, case_id)
                status = "READY_TO_FOLLOW_UP" if decision == "approved" else "NEEDS_INPUT"
                service.transition(s, case, status)
                return {"outcome": status}
        raise ValueError("Unknown workflow stage")


class CaseRunCoordinator:
    def __init__(self, service, runner=None):
        self.service = service
        self.db = service.db
        self.host = PlatformWorkflowHost(service, runner)

    def request(self, actor, case_id):
        self.service.require(actor, "admin", "reviewer", "operator")
        with self.db.session() as s:
            case = self.service.lock_case(s, actor["tenant_id"], case_id)
            self.service.ensure_no_outbound_inflight(s, case)
            if case.workflow_run_id:
                run = self.service.scoped(s, m.WorkflowRun, case.tenant_id, case.workflow_run_id)
                if run.status not in {"COMPLETED", "CANCELLED"}:
                    return m.row_dict(run)
                if case.status == "READY_TO_FOLLOW_UP":
                    return m.row_dict(run)
            run = m.WorkflowRun(
                id=m.uid(),
                tenant_id=case.tenant_id,
                case_id=case_id,
                thread_id=m.uid(),
                data={"requested_by": actor["id"], "input_version": case.version},
            )
            s.add(run)
            s.flush()
            # thread_id equals workflow identity; the Case mapping is explicit.
            run.thread_id = run.id
            case.workflow_run_id = run.id
            self.service.transition(s, case, "RESEARCHING")
            return m.row_dict(run)

    async def run(self, tenant, run_id):
        token = m.uid()
        now = m.utcnow()
        lease_seconds = max(self.service.settings.lease_seconds, self.service.settings.max_case_seconds + 30)
        with self.db.session() as s:
            run = self.service.scoped(s, m.WorkflowRun, tenant, run_id)
            if run.status in {"COMPLETED", "CANCELLED"}:
                return {"status": run.status}
            changed = s.execute(
                update(m.WorkflowRun)
                .where(
                    m.WorkflowRun.tenant_id == tenant,
                    m.WorkflowRun.id == run_id,
                    or_(m.WorkflowRun.lease_until.is_(None), m.WorkflowRun.lease_until <= now),
                )
                .values(
                    lease_token=token,
                    lease_owner="coordinator",
                    lease_until=now + timedelta(seconds=lease_seconds),
                    status="RUNNING",
                )
            )
            if changed.rowcount != 1:
                return {"status": "LEASED"}
            s.refresh(run)
            case_id = run.case_id
            refresh = run.data.get("refresh_approval", False)
            input_version = run.data.get("input_version", 1)
            case = self.service.lock_case(s, tenant, case_id)
            if case.status == "FAILED":
                self.service.transition(s, case, "RESEARCHING")
        self.host.active_leases[run_id] = token
        owner_task = asyncio.current_task()

        async def heartbeat():
            try:
                while True:
                    await asyncio.sleep(min(30, max(0.1, lease_seconds / 3)))
                    now = m.utcnow()
                    with self.db.session() as session:
                        changed = session.execute(
                            update(m.WorkflowRun)
                            .where(
                                m.WorkflowRun.tenant_id == tenant,
                                m.WorkflowRun.id == run_id,
                                m.WorkflowRun.lease_token == token,
                                m.WorkflowRun.lease_until > now,
                            )
                            .values(lease_until=now + timedelta(seconds=lease_seconds))
                        ).rowcount
                        if changed != 1:
                            owner_task.cancel()
                            return
            except asyncio.CancelledError:
                raise
            except Exception:
                owner_task.cancel()

        beat = asyncio.create_task(heartbeat())
        try:
            async with checkpoint_saver(self.service.settings.checkpoint_url) as saver:
                graph = build_workflow(self.host, saver)
                config = {"configurable": {"thread_id": run_id}}
                snapshot = await graph.aget_state(config)
                if refresh and snapshot.values:
                    await graph.aupdate_state(
                        config,
                        {
                            "decision": {},
                            "decision_valid": False,
                            "input_version": self.service.get(tenant, case_id)["version"],
                        },
                        as_node="deterministic_quality_gate",
                    )
                    snapshot = await graph.aget_state(config)
                decision = None
                if snapshot.values.get("approval_id") and "approval_interrupt" in snapshot.next:
                    with self.db.session() as s:
                        approval = self.service.scoped(s, m.Approval, tenant, snapshot.values["approval_id"])
                        if approval.decision and approval.status != "INVALIDATED":
                            decision = {"approval_id": approval.id}
                result = await asyncio.wait_for(
                    invoke_workflow(
                        graph,
                        {
                            "tenant_id": tenant,
                            "case_id": case_id,
                            "workflow_run_id": run_id,
                            "input_version": input_version,
                            "max_rounds": self.service.settings.max_research_rounds,
                        },
                        decision,
                    ),
                    timeout=self.service.settings.max_case_seconds,
                )
                snapshot = await graph.aget_state(config)
                status = "WAITING_HUMAN" if snapshot.next else "COMPLETED"
            with self.db.session() as s:
                row = self.service.scoped(s, m.WorkflowRun, tenant, run_id)
                now = m.utcnow()
                changed = s.execute(
                    update(m.WorkflowRun)
                    .where(
                        m.WorkflowRun.tenant_id == tenant,
                        m.WorkflowRun.id == run_id,
                        m.WorkflowRun.lease_token == token,
                        m.WorkflowRun.lease_until > now,
                    )
                    .values(
                        status=status,
                        lease_token=None,
                        lease_until=None,
                        lease_owner=None,
                        data={**row.data, "refresh_approval": False},
                        finished_at=now if status == "COMPLETED" else None,
                    )
                ).rowcount
                if changed != 1:
                    raise ServiceError("Workflow lease lost")
            return {"status": status, "workflow_run_id": run_id, "outcome": result.get("outcome")}
        except BaseException as exc:
            with self.db.session() as s:
                run = self.service.scoped(s, m.WorkflowRun, tenant, run_id)
                changed = s.execute(
                    update(m.WorkflowRun)
                    .where(
                        m.WorkflowRun.tenant_id == tenant,
                        m.WorkflowRun.id == run_id,
                        m.WorkflowRun.lease_token == token,
                    )
                    .values(
                        status="FAILED",
                        lease_token=None,
                        lease_until=None,
                        lease_owner=None,
                        data={**run.data, "error_class": type(exc).__name__},
                    )
                ).rowcount
                if changed:
                    case = self.service.lock_case(s, tenant, case_id)
                    self.service.transition(s, case, "FAILED")
                    self.service.event(s, tenant, case_id, "workflow.failed", {"error_class": type(exc).__name__})
            raise
        finally:
            beat.cancel()
            with suppress(asyncio.CancelledError):
                await beat
            self.host.active_leases.pop(run_id, None)
