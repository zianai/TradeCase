# Independent security review: final platform boundaries

Date: 2026-10-28. Reviewer: runtime_workflow, independently reviewing the root- and
persistence-owned files below. A separate outbox_check agent independently reproduced
and rechecked the delivery race. This review is bound to the recorded SHA-256 bytes;
it is not a whole-product penetration test or production authorization.

## Reviewed subjects

- `src/tradecase/platform/services.py`: `184193d96c762efef973a142f56fb08afebce92d415254edf98c5ac189ffe92f`
- `src/tradecase/platform/api.py`: `936133b27911f393a4df2c4c32cb901e2f8d0052b6e41c2e4094e8cd8b66b37c`
- `src/tradecase/platform/actions.py`: `7890297186b2a81dcdb17bb54ae2e906b3c4285f9a94758475e6438596e96f90`
- `src/tradecase/platform/source_intake.py`: `374277e7722b5666b100fd3e031c4f871e16ff3f856d87646234f1effe6cb81a`
- `src/tradecase/platform/source_cache.py`: `96e5ebf1bb03adafb39f8195ad4f1df03dae519e3e798c3b27cb6bb54700f776`
- `src/tradecase/platform/knowledge.py`: `6b99da2f889eaac1efa4e951f3d11fae2549bf55b9f7bc964d2a796179f05f24`
- `src/tradecase/platform/workers.py`: `ebeb7f018267910a21bed9e4da16a89eeefc0540f0a97f066ab6e77d4b22f23a`
- `src/tradecase/platform/maintenance.py`: `82241cb874a324a5ee230f8f21ed3153ba7b5390f050212d803f022edb5f7ac4`

The reviewer did not modify these eight subjects. The reviewer implemented the
coordinator draft-write fence and its integration regression; that change is listed
separately in the JSON evidence and is not represented as independent self-review.

## Findings and disposition

1. **P1: retention omitted reviewed materializations. Resolved.** A temporary test
   database demonstrated that purge returned `PURGED` while private inquiry copies
   remained at `tenant/review-*/case_id` and, after a simulated interrupted build,
   `tenant/review-*/.review-build-*/case_id`. Retention now enumerates these bounded
   layouts and the ordinary Case directory, checks every path for symlinks before
   deleting anything, and preserves unrelated Case directories. Historical review,
   crash staging and symlink regressions pass. Object garbage collection remains a
   separate operation requiring explicit writer quiescence and a cross-tenant
   reference scan.
2. **P1: draft decisions bypassed the delivery freeze. Resolved.** A blocking FakeMail
   probe showed `request_changes` incrementing the Case version while an action was
   `DISPATCHING`. Reverse-order probes showed a negative decision leaving an earlier
   mail approval usable before the workflow resumed. External authorization now
   requires the current, unexpired approved draft review at approval creation,
   approval decision, enqueue and dispatch. Draft decisions reject in-flight or
   uncertain delivery; negative decisions atomically invalidate mail/CRM approvals.
   The resumed workflow also checks the same Case lock before a draft version write.
   The original admission now returns 403, delayed negative-decision authorization
   returns 403, and legacy in-flight mutation tests return 409.

3. **P2: stale queued actions could strand retention. Resolved.** Explicit cancellation
   checks admin/reviewer authority, tenant, current Case version and `PENDING` state
   under the same Case lock used by dispatch. Closing a Case also atomically cancels
   queued actions. In-flight and uncertain deliveries still require reconciliation.
   Independent probes rejected unauthorized roles, foreign tenants, stale versions,
   forged status fields and cancellation during an actually blocked FakeMail call.
   That separately approved sandbox action completed exactly once after release.

The final review also checked tenant-filtered resource and snapshot access, exact
Case/artifact/version approval binding, idempotency payload checks, immutable object
hashes, role restrictions, honest manual-snapshot provenance, tenant-scoped cache and
knowledge retrieval, and current-approval/due-task worker recovery. Earlier guards
for streamed upload size limits, concurrent dispatch, draft-edit freezes, and late
provider receipts remain covered by the final API/action suite.

## Executed verification

The frozen targeted suite passed **55 tests in 57.53 seconds**:

```text
.venv/bin/python -m pytest tests/platform/test_actions.py tests/platform/test_api.py tests/platform/test_source_intake.py tests/platform/test_source_cache.py tests/platform/test_knowledge.py tests/platform/test_maintenance.py tests/platform/test_workers.py tests/platform/test_coordinator.py -q
```

It covers API/actions, source intake/cache, knowledge, maintenance, worker recovery
and coordinator integration; maintenance contributes 18 tests. Before the additive
pending-cancellation change, a separate outbox
reviewer reran the 11 action tests and independently confirmed the original and
reverse race paths are denied with zero FakeMail calls. The final suite also covers
the three new cancellation regressions. Eight additional API probes
rejected viewer/operator decisions (403), foreign tenants (404), incorrect hashes or
Case versions (409), and forged reviewer/tenant/scope fields (422); the approval
remained pending and unchanged.

Exact hashes, outcomes and limits are recorded in
[`independent-review-runtime.json`](../evidence/full-delivery/independent-review-runtime.json).
The additional probe outcomes are in
[`independent-approval-probes.json`](../evidence/full-delivery/independent-approval-probes.json)
and [`independent-cancel-probes.json`](../evidence/full-delivery/independent-cancel-probes.json).

No remaining reproducible P1 was identified within these subjects and scenarios.
Every action probe used temporary SQLite databases, synthetic fixtures and fake
connectors. No real messages, CRM writes or paid model/API calls were executed.
Live provider contracts, credentials, source licenses, TLS/reverse-proxy deployment,
production retention and backups still require deployment-specific validation.
