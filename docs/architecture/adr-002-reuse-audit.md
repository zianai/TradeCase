# ADR 002: Reuse and gap map

| Area | Baseline | Workbench extension |
|---|---|---|
| Inquiry/.eml parsing | tradecase.ingestion, CaseInput; retain raw bytes/hash | immutable DB inquiry and object reference |
| Entities/evidence | buyer_research, models, conflict/strict validation | normalized tenant-scoped claims/sources/links and snapshots |
| Scoring | assessment.py deterministic rules | invoke existing assess_case; store versioned dimensions |
| Compliance | compliance.py country/platform rules | invoke check_case; persist risk finding version/source |
| Draft/report | reporting.py conservative compose/QA/report | version history, human edit, hash-bound decisions, exports |
| Public reads/SSRF | providers.py pinned DNS/redirect checks | permissioned semantic registry, budgets, unavailable adapters |
| Skills | trade-inquiry, buyer-research, trade-compliance | thin runtime mappings; no duplicate domain Skills |
| Persistence | journaled file store | SQLAlchemy/PostgreSQL + Alembic; keep CLI compatibility |
| Scheduling | none | Task leases + attempts; ARQ wakes one workflow coordinator |
| Agent runtime | host-agent only | OpenAI Agents SDK adapter + explicit fake; no new inference loop |
| Workflow | host ordered commands | persistent LangGraph, bounded gaps, approval interrupt |
| Product UI/API | none | FastAPI + Next.js; Case/Inbox/Follow-ups/Sources/Settings |
| External writes | SMTP blocked | default-off outbox, explicit scope, uncertain-receipt reconciliation |

Prior optional-source licensing restrictions are retained. No Multica, Superleads or Launchfit source is copied. Consumer CLI subscriptions are not treated as API entitlement.
