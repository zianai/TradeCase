# ADR 006 — Independently executable Visual Task contract gates

Date: 2026-10-30. Scope: the user's request for durable TradeCase ↔ Creative Engine compatibility checks. External effects: none.

Both repositories vendor the same immutable versioned consumer contract. The consumer gate exercises its actual HTTP adapter against that release; the provider gate exercises its actual HTTP server against the same requests and minimum responses. Neither imports the other's internals nor fetches a floating counterpart branch. Optional local pair testing uses both current implementations via public HTTP.

Allow additive response fields and unrelated capabilities. Pin required request, response, authorization, cost, idempotency, provenance and approval semantics. Protect released artifact bytes against the PR/push baseline; incompatible changes require a new release with a coexistence/migration policy. Keep image v1 usable when video or 3D is introduced. Unknown outcomes never grant retry or approval authority.

No production service, model key, browser session or mail transport belongs in these tests. A CI failure is not a repository merge prohibition until GitHub required-status-check rules are actually configured. Deployment state and executed evidence are recorded in docs/VISUAL_CONTRACT_CI.md and docs/VISUAL_CONTRACT_REPORT.md.
