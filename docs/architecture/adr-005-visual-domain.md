# ADR 005 — Optional Visual Domain

Date: 2026-10-30. Authorized by the user's incremental upgrade request.

The current user request supersedes the historical V1 exclusions; it does not authorize paid generation, customer delivery or overwriting pre-existing work. Development branch: codex/tradecase-visual-tasks, starting commit 11147c12d21305862ad67a2bd439e7c486e06d5a. Existing controlled-access modifications remain local and outside this change's commits.

Product Truth is an immutable, tenant-scoped statement of product information and its provenance/status. A VisualAsset is a communication artifact, never a Source or Claim. Product facts are neither inferred from generated pixels nor merged into the buyer evidence score. Source images, logos and output assets have separate provenance and permission records.

The existing LangGraph retains Case sequencing and its TaskManager retains node attempts. Optional visual nodes only record suggestions and dispatch readiness; the Creative Engine owns generation workers and generic visual QA. A durable visual run records submission identity, remote references and synchronization. A bounded recovery poll resumes existing runs; it never starts a second research workflow. Engine failure must not block buyer analysis.

Plan approval authorizes a versioned plan, changes and budget. Asset approval independently authorizes exact returned asset bytes for business use. A remote completed status is not approval. Any revision or stale truth requires a new review. Proposal and draft changes create immutable revisions and invalidate ordinary draft approval. Mail permissions remain separate and disabled by default.

The adapter uses the actual sibling Creative Engine API rather than importing its internals. Provisional/unsupported remote features fail closed. HTTP service integration with a mock provider is recorded separately from live model generation. No paid provider is exercised by upgrade validation.

Original tests and new local regression tests remain in the workspace. The user's earlier instruction not to submit test sets is retained for commits; test execution summaries are documented, test fixtures and generated evidence are not pushed.
