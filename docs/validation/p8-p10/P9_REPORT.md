# P9 TradeCase evidence-driven fixes

Tested engineering subject: `381fbc182429562046461dd518bcb4d8851ff77e`. Local failures, rather than unavailable E3 quality scores, determine this change set.

- Browser regressions found that the frontend overwrote the evidence API conflict list with the older Case conflict list. It now uses the authoritative evidence response. A claim opens its exact link excerpt and locator; source relation, expiration and unknown validity remain visible on desktop and mobile.
- Source intake accepts a precise locator, support/contradiction relation and aware expiry. Expired source material cannot be promoted as current supported reviewer evidence. Existing source/draft version changes continue to invalidate exact approvals.
- A failing canary test reproduced raw unknown request values in FastAPI validation errors. Errors now retain only safe request location, error type and generic correction text; arbitrary keys and values are excluded. Independent root review found and prompted a second negative case for secret-like keys.
- Independent root review also required real-data reauthorization and retention on pilot export. Regression now proves grant revocation, expired retention and legacy unknown provenance cannot export through this adapter.
- Model results persist actual SDK input/prompt/Skill byte hashes. No separate orchestration loop was introduced. The existing TaskManager lease fencing, real Redis/ARQ duplicate-message path, source URL guard and immutable HTTP contract are retained and rerun.

Failure-before records remain under `evidence/browser-02`, `browser-03`, and `negative-errors-before`; corrected records and final commit-bound runs are mapped in `acceptance-results.json`. No real buyer accuracy, business conversion or time-saving uplift is claimed. Human design approval remains pending.

A second independent review reproduced the mixed-source issue: a synthetic Case could gain an unknown manual source. The corrected scope binds every current source/hash/rights record and uses a separate export grant. Missing source-level synthetic provenance defaults to sensitive/unknown, not synthetic. Tests prove intake grant rejection, post-grant source addition rejection, rights-change-during-read conflict, and revocation-before-return rejection. The real browser now verifies the manual-source pilot export is blocked while keeping source review readable.
