# P7 local validation and next-run boundary

This branch implements reversible E0/E1 engineering only. No production deployment, real-data import, paid model call, outbound send, GitHub push/merge, or visibility change is approved. Synthetic test actors and original-mode fixtures are software test inputs, never evidence of a real human approval or genuine product.

## Deterministic authorization

The private OS operator directory contains `grant.json`, `isolation.json`, and `context.json`, all mode 0600, with no symlink path. The process must have `ALLOW_TEST_LIVE=on` and the exact SHA256 of the approved grant through a system-specific environment variable. Business HTTP, model text, and Agent tools cannot write these records or pins. The OS administrator is a trusted boundary; this is not a cryptographic identity service.

A grant binds run/system/tenant/environment/case/dataset, plan/input/rights/provider configuration hashes, classification/export rights, exact action/provider/model/domain, UTC expiry, request/image limits, one attempt, and a finite monetary reservation. Image and Vision actions require independent capabilities. Public reads additionally pin every source URL, including robots/redirect URLs, in `grant.source_urls`; an approved domain is not permission to fetch arbitrary pages.

Each product owns its own transactional reservation ledger. Concurrency cannot overspend the grant. Unknown receipts retain their reserved liability and block new calls, including after process restart. No automatic remote reconciliation or repeat payment is implemented: an operator must first obtain provider-side evidence and a separately reviewed reconciliation procedure. Do not delete/edit a ledger to bypass this stop. Reported model prices and costs are estimates, not verified current tariff or billing ceilings.

Preflight is local and has no network side effect. Exit 2 means blocked, exit 0 means locally eligible, never proof of a successful live request. Native adapters validate again immediately before calling. OpenAI endpoints are pinned and SDK retries disabled. Browser-account extraction and remote image batch calls remain blocked.

## Data and review boundaries

Engine API 1.0.0 is frozen. Business apps own evidence, original rights, product/buyer facts, and approval versions; Engine owns raster work, receipts, QA and asset IDs. No shared business DB is introduced. Generated assets cannot establish buyer evidence or original product truth. Plans and finished assets require separate reviews. Deterministic file QA does not imply semantic image QA; skipped Vision is not pass.

Private real data and current rates must be authorized separately before any live test. A valid paid synthetic test grant does not authorize customer/quote export. Two independent business reviewers and a matched manual time baseline are still absent. All business metrics are not_evaluable; no rollout or listing publication is authorized.

## Reproduce

See the coordinator's P7_RELEASE_INDEX.md for exact implementation SHAs, commands, run manifests and failures/corrections. Tests run with empty credentials, explicit disposable data paths and an OS network policy permitting loopback only. Cached Docker images use --pull=never. Python and Node dependencies are already installed; the local run never needs a package download. The coordinator is an evidence folder, not a service or a fourth application.

## Native command

```sh
python -m tradecase.p7_policy --system tradecase --request docs/validation/p7/request.synthetic.json --upper-usd 0.01
```

Native settings: `TRADECASE_P7_ROOT`, `TRADECASE_P7_APPROVED_GRANT_SHA256`. None are configured for an authorized live run here.
