# ADR 003 — Durable Case workflow and bounded SDK research

Date: 2026-10-28. Status: implemented; offline validation described below. No paid
API request or external write was executed for this ADR.

## Boundaries and integration

The existing `tradecase` business modules, three canonical Skills and legacy CLI
remain the source of parsing, scoring, compliance, drafts and reports. New
`platform.workflow` invokes `WorkflowHost.step`; the service implements those
steps against the existing functions and transactional database. It does not
reimplement their business rules.

A single LangGraph `StateGraph` determines business dependencies: parse, normalize,
plan, three independent research branches, merge, conflict/evidence gate, bounded
supplementary research, assessment, compliance, draft/QA, approval, report,
action policy, follow-up and update. A TaskManager only leases work and records
attempts. There is no SDK leader agent and no second scheduler deciding Case status.
Nodes have no LangGraph retry policy; technical retries belong to TaskManager.

The graph checkpoint contains tenant/Case/workflow IDs, durable result references
and small summaries. It refuses unknown state fields and updates over 16 KiB.
`workflow_run_id` is the stable `thread_id`; it cannot be reused with another Case
or tenant. `invoke_workflow` resumes an existing cursor and returns a completed
cursor for duplicate jobs. The coordinator must hold a database lease throughout
invocation; the graph is not a substitute for that lease.

Production uses `AsyncPostgresSaver` with explicit deployment `.setup()`.
Development uses `AsyncSqliteSaver` in a named file, including actual separate
process restart tests. In-memory savers are not offered by the deployment factory.
Business records, approvals and outbox data remain authoritative even when a
checkpoint is present.

## Human decisions

`prepare_approval` is a separate idempotent service node before `interrupt()`;
resuming an interrupt therefore repeats no pre-interrupt side effect. The resume
payload references an existing approval. `validate_decision` must reload that
record, check tenant, reviewer authority, Case version, evidence version and exact
artifact hash, and return the validated decision. An `approved` field from the
caller or model is insufficient. The outbound policy rechecks authorization again.

Rejected decisions and evidence requests that cannot legally run further research
must remain review/input states. Change requests create a bounded revision and a
new approval interrupt. Maximum research/revision rounds are enforced by the graph
(0–3 configurable, default 1) even if the host erroneously requests more. Failed
QA remains reviewable but the service must prohibit approving/sending it until a
valid revision is available.

## Runtime and evidence

`AgentRunner` exposes typed requests/results, capabilities, cancellation, resume
and redacted events. `FakeAgentRunner` is always synthetic and labels supplied
fixture sources synthetic. A missing source produces PARTIAL and an explicit gap.
It never fabricates a successful live research run.

`OpenAIAgentRunner` uses actual OpenAI Agents SDK `Agent`, `Runner.run`,
`FunctionTool`, `ModelSettings` and `RunConfig`. An injected SDK `Model` drives
unit tests through the real SDK loop without network/keys. Live calls require
`live_enabled`, a selected model, a positive cost budget and an operator-supplied
conservative token price upper bound. No price is guessed. SDK tracing is disabled
and sensitive trace data is disabled. Exceptions are logged by class only.

The adapter limits SDK turns, wall time, tool calls, per-domain calls, domain
spacing, per-tool time, output tokens and cumulative token/cost budget. Before
calling the model it checks a conservative UTF-8 byte bound including prompt,
tool definitions, output schema and structural allowance, plus max output tokens.
Hidden server conversation/prompt context is prohibited. Provider usage is checked
again after each response. An uncertain request retains its cost reservation and
marks the estimate; cancellation cannot assert the provider performed no billable
work. Pricing configuration still requires operational maintenance when rates
change. This is a conservative spend guard, not a provider billing reconciliation.

SDK continuation is explicitly unsupported because no durable provider Session
is stored. A Task can safely retry with a new attempt/run and retain verified
prior outputs; workflow checkpoint recovery does not pretend to resume an SDK
process. Local cancellation cancels the active coroutine and reports its limits.
`stream_events` returns the adapter's redacted execution events; continuous live
streaming capability is false. Persisted service events supply application SSE.

Facts require source IDs and an exact quotation found in an immutable hashed
snapshot. Returned SDK sources must exactly match supplied or observed tool
sources; fabricated or modified source records fail validation. This proves
citation integrity, not factual truth. Entity resolution/scoring/conflict
handling still belong to deterministic services and human review. Live results
reject synthetic source snapshots.

## Tools and Skills

Only six read-only semantic tools can be registered. Tool authority is set in the
request before model execution; tool names, live availability, source permission,
domain allowlist, time and cost are enforced outside model instructions. Untrusted
source text cannot add a sending tool. Search, browser, registry, knowledge and
extraction sources default to unavailable until an authorized adapter is installed.

The optional public `fetch_page` adapter reuses the existing `ContentReader`
(SSRF/DNS pinning, redirect revalidation, robots, secret-URL rejection, size/time
bounds). It does not bypass licenses or authenticated sites. Tool bodies are marked
untrusted regardless of the supplied output flag. Available fetch does not imply
coverage of paid or official registries.

`SkillAdapter` reads the existing `buyer-research`, `trade-compliance`, and
`trade-inquiry` Markdown byte-for-byte and reports hashes. Skill selection rejects
unknown names, path traversal and symlink targets. Runtime-specific instructions
are a thin wrapper; no prompt holds essential authorization or business state.

## Exact tested dependencies and official references

The repository lock pins OpenAI Agents SDK 0.24.0, OpenAI SDK 3.40.0, LangGraph
1.2.18, checkpoint core 4.3.1, SQLite checkpoint 3.1.2 and Postgres checkpoint
3.2.0. API signatures were inspected from these installed packages and exercised
with the real SDK and graph implementations.

- [OpenAI Agents SDK guide](https://developers.openai.com/api/docs/guides/agents/sdk)
- [Agents SDK running agents](https://openai.github.io/openai-agents-python/running_agents/)
- [Agents SDK model interface](https://openai.github.io/openai-agents-python/ref/models/interface/)
- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)

Actual automated evidence: `tests/platform/test_runtime.py` and
`tests/platform/test_workflow.py`. These test real SDK execution with a fake
model, a two-turn tool call, injection isolation, citation rejection, unavailable
sources, budgets, credential-free defaults, redaction, Skill hashes, concurrency,
interrupt/revision/rejection, tenant-bound cursors, duplicate jobs, SQLite reopen
and separate process restart. PostgreSQL recovery and live model access need their
own deployment/environment test; unit test success is not evidence for either.

A controlled API smoke is available only through explicit operator invocation:
`python -m tradecase.platform.runtime --authorize-live --model MODEL
--usd-per-token-upper-bound RATE --max-cost-usd 0.05`. It uses no customer data,
permits no tools, sends no email and prints a redacted execution receipt. RATE
must be a checked conservative USD/token rate for the selected model. This
command was not run with real API credentials during implementation.

## Reviewer-bound inputs and retained business gates

`ReviewInputsService` closes the boundary between newly captured database evidence
and the retained assessment/compliance code. An admin/reviewer selects existing
Claim–Source links and supplies entity bindings, discrete signals, seller
attributes and scoped versioned rules. Every binding independently confirms source
permission and its source role. URL, capture time, claim text, exact quotation and
snapshot bytes are derived from existing tenant/Case records and content hashes;
the review request cannot replace them. Internal knowledge cannot be relabelled
as an official public source. Claim meaning, source authority, seller declarations
and current rule applicability remain explicit human judgments.

The full proposed bundle is passed through `calculate_assessment`,
`evaluate_compliance` and the original cross-artifact validator before it commits.
The bundle is saved as an immutable artifact with reviewer identity, source
provenance and idempotency binding. Submission bumps the Case version, invalidates
approvals and cancels the old workflow. A new run materializes this exact review
version in an atomic, disposable compatibility directory; the old directory and
review artifacts remain available. Deterministic scoring and current-time rule
checks consume the bundle. Already reviewed sufficient research is reused without
creating a pretend model call. Research cannot become COMPLETE from SDK coverage
alone: the original assessment must pass and unresolved conflicts must be absent.
Historical risk findings are retained with `data.active=false`; current findings
carry the current Case version.

`tests/platform/test_review_inputs.py` exercises manually uploaded, explicitly
non-live contract-test snapshots under the real (non-synthetic) data schema. It
proves reviewed bindings reach the original 70-point scoring and both rule checks,
then the graph, draft approval and follow-up. It also checks quote/link mismatch,
source-role escalation, stale versions, tenant/role isolation, current-rule
confirmation, immutable source fields and old approval invalidation. These tests
prove integration and gates, not that their test statements are true on the URLs
or that live legal/regulatory research occurred.
