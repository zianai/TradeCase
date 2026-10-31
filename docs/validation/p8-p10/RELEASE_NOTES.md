# TradeCase P8–P10 local release candidate

Code subject: `381fbc182429562046461dd518bcb4d8851ff77e`. Branch: `codex/p8-p10-tradecase`. Base: `46d65cd5bce416e5036221a95c353eb13b1b6ef4`. The final report commit is recorded by the coordinator release index; the tests here name the immutable code commit rather than a future self-referential report SHA.

Adds scoped pilot import/export, exact source locator/conflict/expiry UI, SDK prompt/input/Skill provenance, request-error redaction, tenant-scoped credential rotation/revocation and state-count monitoring. Extends recovery proof for approval/object hashes and delivery uncertainty. Adds reproducible isolated browser and local TLS acceptance plus parameterized CE HTTP smoke. Existing workflow, SDK, Skills and 1.0.0 protocol stay in place.

No database schema migration is introduced. Existing migrations are exercised on disposable copies. Rollback uses a verified database/object/checkpoint backup with the prior release, not a production downgrade. New pilot/source/AgentRun fields use existing JSON records; legacy missing provenance remains explicitly missing. Existing real Cases without pilot provenance cannot use the new pilot export route.

The exact per-test result map is `acceptance-results.json`. E0/E1 completion does not approve business quality, actual cost savings, production operation or external sending. Real-data/reviewer and high-impact tasks remain BLOCKED_EXTERNAL. No push, tag publication or deployment was performed.
