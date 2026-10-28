# ADR 001: Extend the existing business kernel into a Case workbench

Date: 2026-10-28. Accepted for implementation by the current direct user request.

The repository baseline is 3a4f8b4 on codex/tradecase-v1, a descendant of e446f94. The clean baseline passes 347 tests including all seven synthetic Case CLI validations. Development branch: codex/tradecase-complete. The supplied full implementation plan is copied unchanged to docs/tradecase-full-implementation-plan.md.

The current request supersedes prior V1-only exclusions in AGENTS.md, docs/DECISIONS.md and archived specifications. Those historical choices remain preserved as history. We add a platform package; we do not replace existing parsing, assessment, compliance, reporting, providers, CLI or canonical Skills. No production, paid API, real mail or CRM action is performed by this development task.

PostgreSQL is the business record authority for the workbench. The file CaseStore remains the supported standalone CLI format and a deterministic compatibility export/materialization used by existing business functions. It is never a second scheduler. New platform CLI commands call the same services as HTTP. Existing commands retain their documented file semantics.

CaseService alone changes Case status using guarded transitions. LangGraph owns business sequencing. TaskManager owns durable work/attempts, leases, fencing, bounded retries, cancellation and results, never business conclusions. ARQ only wakes the coordinator; DB work survives lost/duplicate queue messages. A stable workflow_run_id maps a Case to LangGraph checkpoints; AgentRun is one model execution attempt, never a Case or Task identity.

SQLAlchemy supports PostgreSQL production and SQLite local tests. Alembic owns migrations. Local content-addressed storage and S3 implement one interface; source snapshots and immutable artifacts have SHA256 verification. Tenant checks apply in every service/resource query including events and source bodies. Production uses hashed bearer identities provisioned by an administrative CLI, with RBAC; browser code never contains service credentials.

Approval records bind Case version, immutable artifact hash/version and scope. Editing invalidates pending/approved reviews. External writes recheck authorization transactionally, use a persistent outbox, and fail closed after an uncertain receipt. Real sending is disabled by default and never inferred from draft approval. Model/page content cannot grant authority.

Limitations are recorded by execution evidence, separately for offline adapters, local service integration and live external sources. No synthetic result is represented as online success.
