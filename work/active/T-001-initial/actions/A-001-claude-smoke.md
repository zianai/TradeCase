---
action_id: "A-001-claude-smoke"
target: "Existing authenticated Claude Code first-party account; one print-mode invocation"
environment: "Local TradeCase repository; restricted tools; synthetic fixture only"
payload_scope: "Saved host-validation prompt; max-budget-usd 1; Read and three bounded TradeCase CLI operations"
subject: "sha256:8180b62246097556be227c3bdefabb12b55f8500159a3c4054486fc950c51eb0"
subject_ref: "docs/host-validation-prompt.txt"
authorization_basis: "direct-human-instruction"
authority_ref: "docs/evidence/P6/claude-invocation.json"
one_shot: true
idempotency_key: "not supported; no automatic retry"
expires_at: "2026-10-27T16:30:03.778614+00:00"
timeout_seconds: 180
status: failed
observation: "Exit 1; result Not logged in; 0 input/output tokens; total_cost_usd 0; no Case created"
reconciliation_result: "no-effect-confirmed"
reconciliation_ref: "docs/evidence/P6/claude-stdout.json"
compensation: "No reversal of model usage; stop at budget or timeout; no retries without fresh authority"
retry_allowed: false
---

# Authorized Claude smoke

The exact user prompt is docs/host-validation-prompt.txt. The invocation metadata
records exact CLI arguments and preserves the human's bounded authorization.
No credentials, private correspondence or real business data are supplied.
A budget flag bounds runtime model use; actual provider billing is not independently visible.

Direct human authorization: “允许一次，调用预算 $1”. The process returned Not logged in, zero token/model usage and zero reported cost; no Case/business tools ran. No-effect-confirmed refers to observable model/business execution, not an independently audited provider bill. No retry was performed.
