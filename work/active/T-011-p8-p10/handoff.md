---
task_ref: work/active/T-011-p8-p10/task.yaml
subject: git:381fbc182429562046461dd518bcb4d8851ff77e
subject_paths: [".github/workflows/check.yml", ".gitignore", "Makefile", "frontend/components/workbench.tsx", "frontend/tests/live-e2e.spec.ts", "frontend/tests/p8-provenance.spec.ts", "ops/p8_browser_acceptance.py", "ops/p8_ce_http_smoke.py", "ops/p8_tls_acceptance.py", "src/tradecase/platform/api.py", "src/tradecase/platform/cli.py", "src/tradecase/platform/coordinator.py", "src/tradecase/platform/pilot.py", "src/tradecase/platform/review_inputs.py", "src/tradecase/platform/runtime.py", "src/tradecase/platform/services.py", "src/tradecase/platform/source_intake.py", "tests/platform/test_deployment.py", "tests/platform/test_p8_p10.py", "tests/platform/test_runtime.py", "tests/unit/test_p7_policy.py"]
---

# Local handoff to the three-system coordinator

The source/test subject above is the final engineering commit. It passes make check (509 passed, four opt-in infrastructure skips), separate actual PG/Redis tests (4 passed), immutable contract tests (43 passed), browser tests (18 passed), frontend build, local TLS and bounded Git secret scan. Command/exit/source/log-hash records are in docs/validation/p8-p10/evidence/final-v2-*; acceptance-results.json maps 28 IDs. Final report commit changes documentation/evidence/task metadata only.

Root independent review found request key reflection and insufficient real/mixed-source export authorization. Both are fixed with negative tests. Pilot export now requires a separate pinned current source/claim/link/version/rights subject, rechecked after reads; manual source classification never inherits Case.synthetic. New scope endpoint returns no claim/title/quote text. Real business statistics remain null.

The coordinator owns aggregate simultaneous HTTP, outage/SSE and final 73-case matrix, independent final review and release index with all exact final repository SHAs. Cross-system rows in this repo are deliberately partial plus component evidence, not full aggregate passes. No remote push or deployment occurred. E3 inquiry/reviewer/timing tasks remain BLOCKED_EXTERNAL. Human design approval and business acceptance are pending.

A read-only CE independent review against bf18ba8b919e33f08a68749380c474c40a21c621 is recorded in docs/validation/p8-p10/CE_INDEPENDENT_REVIEW.md; its receipt downgrade finding was closed by CE's owner. Do not treat agent review as human approval.
