# TradeCase authorized synthetic live followup

Engineering result: a real OpenAI Agents SDK response was validated, persisted through the existing TaskManager, assembled by the existing local LangGraph, and displayed in the actual desktop/mobile review UI. The Case is synthetic and `NEEDS_REVIEW`; its approval is `PENDING`; external sends are zero. This is E2 synthetic verification, not E3 business acceptance or a real customer success.

Code: `d6c11f463f79bba51ff0ae303f3c55a7c9253ac2`. The paid calls ran before that commit in a dirty worktree based on `42ed8e40729c15f50adedcfc69eeea4b645641fc`. The pre-call offline runner captured tracked patch `c9eddc017e60333c5e35a12044684e524f85e64149d841b87fed2b417d348a4c`. `execution-source.json` records the runtime file hash and exact provenance limit: no complete untracked-file snapshot was captured before the call. We do not claim the paid calls ran a later commit. Full actual synthetic request/response bodies are retained.

## Execution and findings

| Attempt | Actual provider calls | Observed outcome |
|---|---:|---|
| 01 | 0 | Frozen request failed locally because optional numeric defaults changed representation on JSON reload. Reconciliation confirms no key read, receipt or reservation. Canonicalize the Pydantic request before hashing. |
| 02 | 1 | HTTP 200, 3,451 tokens. Native validator rejected source-identity changes: model invented an inquiry source and changed supplied source metadata. Preserve this rejected response and its cost. |
| 03 | 1 | HTTP 200, 3,347 tokens. Explicit immutable-source instructions, correctly classified unverified fixtures, and an explicit inquiry snapshot produced a valid `PARTIAL` result: 6 claims, 2 exact sources, 7 open questions and unresolved same-name entity conflict. |

The strict source-identity validator was preserved. Runtime fixes keep synthetic provenance and estimated-cost labeling accurate for both rejected and accepted real responses. Regression tests exercise both exact and changed source metadata. The initial rejected response's original `synthetic: false` and `cost_is_estimate: false` fields are retained as historical evidence of the fixed bug, not silently rewritten.

Only the identity-research response used the real model. The dedicated operator adapter persists the authentic receipt and replays it into the existing graph; the other research branches remain explicitly `PARTIAL` with no model output. The mail draft is deterministic kernel output, not an LLM draft. The normal synthetic Case runtime still forces offline execution. The test adapter neither approves a decision nor enables sending.

## Budget and authorization

The user's explicit synthetic followup budget is US$10 across systems; TradeCase's hard allocation is US$2. Two fresh grants each capped one request at US$1, with no automatic provider retries. Their exact request, grant hashes, receipt IDs, authority and reconciliation are in the task action YAML files. The first local-only failed preparation did not consume a paid envelope.

Both provider outcomes are known. Total usage is 6,798 tokens. Pricing all tokens at the conservative US$5/M bound gives **US$0.033990 estimated upper cost**, including the rejected call. Runtime reservations total **US$0.226460**; the two grant envelopes total US$2. Actual invoiced cost is **unknown/null**. Base input/output estimates in original summaries exclude cache-write premiums and must not be interpreted as invoices. Raw usage includes cache writes (1,474 and 1,780 input tokens). `cost-reconciliation.json` is the authoritative consolidated explanation, based on the coordinator's official pricing verification at https://developers.openai.com/api/docs/pricing.

The named existing key was read only into process memory; it was never copied into evidence or Git. Private grants, token, SQLite databases and object storage remain outside the repository. All task grants were revoked after use, original executed bytes preserved privately, and the old grant pins now deny preflight. No further paid call is planned.

## Verification

- Final backend suite on the committed code: `final-full-regression/result.json` and `output.log` (512 passed, 4 opted infrastructure skips).
- Static compilation, Ruff, license and inherited-source mapping: `final-static/result.json`, exit 0.
- Focused source/grant regression before retry: 48 passed (`offline-regression/`).
- Actual browser/API verification: 1 passing Playwright scenario covers desktop 1440px and mobile 390px, source modal, six screenshots, no page errors or horizontal overflow, pending approval, outbound disabled, and zero outbound actions (`live-browser/`, `browser/`). Browser checks read persisted real output with public network denied and without API credentials.
- Full project-memory validation passed (`memory-full/`) after marking three historical review/handoff pointers stale; the historical documents were preserved.
- Root independent code/action review found no blocking finding within its stated scope; the task review records its exact subject and limitations. It is not human business approval.

Full previous P8–P10 records remain immutable. The four infrastructure checks were not opted into this runtime-only followup; prior P10 PostgreSQL/Redis verification is separate historical evidence. Browser source bytes match the committed helper and test; browser capture preceded the commit and is not presented as a fresh commit-time run.

## Go / No-Go

GO for the bounded synthetic native-SDK-to-pending-review path demonstrated here. NO-GO for promoting this fixture into real buyer facts, auto-approval, sending, production deployment, or claiming every graph branch ran live. Human business acceptance, real data rights and the existing external release conditions remain separate.
