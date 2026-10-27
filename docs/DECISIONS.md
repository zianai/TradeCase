# TradeCase V1 engineering decisions

## ADR-001 — 2026-10-27: incremental upstream derivative

Accepted baseline: `docs/baseline/TradeCase_V1_Codex_Implementation_Spec.md`, SHA256 `4fbea9fb135f653af0f5ff416ab1569a6af6e8fe9b319c6cd72150b4ebd2e23e`.

Preserve the complete Git history of xiongQvQ/-b2b-lead-hunter-skill at `ac27d0ec6627366337423bfcb1ba86c5be5a95a5`; develop locally on `codex/tradecase-v1`. The parent handoff directory is untouched. Retain `scripts/`, `references/`, `templates/`; wrap audited pure functions. No remote fork/push is required or performed.

New code owns versioned business Case contracts, atomic persistence, evidence validation, deterministic scoring and rule checks. Codex/Claude own reasoning and execution. No Agent loop, frontend, service, queue, or model provider client will be introduced. Python 3.11+; Pydantic v2 validates contracts; argparse keeps CLI dependencies small.

SMTP implementation will be disabled, including direct function invocation. Upstream outreach instructions will be replaced at auto-loaded entry points. Pure draft hashing/review functions remain reusable. App gates are not an OS security boundary.

Preserve observed upstream failures as evidence; do not claim upstream lint/demo passed. Legacy files outside the commercial V1 execution path can retain explicitly documented lint debt. New code, adapted files and active wrappers have blocking lint/tests.

Do not install broad AI Hunter dependencies or copy noncommercial sources. Optional crawler/browser integrations are capability-gated and must have an auditable license basis. Online validation is read-only, public sources only; missing login/runtime/licensing is a blocked capability, not a reason to simulate live success.
