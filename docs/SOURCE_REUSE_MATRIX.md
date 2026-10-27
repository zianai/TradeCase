# Source reuse matrix

All B2B rows refer to https://github.com/xiongQvQ/-b2b-lead-hunter-skill at `ac27d0ec6627366337423bfcb1ba86c5be5a95a5`, root MIT copyright 2026 xiongbojian. These source files were inherited through Git, not recreated from descriptions. Destination implementation/test status will be updated at each phase.

| Original file / functions | Target | Nature | License / deps | Test / reason / alternative |
|---|---|---|---|---|
| `scripts/contracts.py` | same file; upstream wrapper | as-is | verified MIT / stdlib | baseline sample contracts pass; keep upstream validators for inherited artifact types; new Case schema supplements them |
| `scripts/extract_contacts.py` | same file; `tradecase` wrapper | as-is | verified MIT / stdlib | baseline smoke passes; preserve format-only email semantics rather than duplicate regexes |
| `scripts/normalize_search_results.py:normalize` | same file; adapter | as-is | verified MIT / stdlib | baseline function passes; do not call defective JSONL file parser |
| `scripts/dedupe_leads.py:domain,merge,unique_list` | same file; candidate wrapper | as-is | verified MIT / stdlib | baseline detects name collision; use explicit entity IDs instead of name-only identity |
| `scripts/customs_verify.py:analyze` | same file; tentative signal adapter | as-is | verified MIT / contracts, stdlib | no-data smoke passes; strip confirmation/score promotion rather than replacing extraction |
| `scripts/evaluate_outreach_drafts.py:body_hash,claim_risk` | same file; draft review wrapper | as-is | verified MIT / contracts, stdlib | deterministic hash smoke passes; no sending |
| `scripts/generate_outreach_drafts.py` | retained legacy source | not-used | verified MIT / contracts, stdlib | inspected; first-touch template not appropriate for reply-specific unknown commercial terms |
| `scripts/validate_artifact.py` | retained legacy source | as-is | verified MIT / contracts | baseline runs; new Case contract validator is separate |
| `scripts/send_smtp.py` | same file, disabled | adapted (planned P1) | verified MIT / stdlib | no sending attempted; all sending disabled before V1 demo |
| `scripts/run_hunt.py` | retained legacy source | not-used | verified MIT / subprocess, requests via scripts | demo fails missing Serper key; no new orchestration loop |
| `scripts/read_jina.py` | retained legacy source | not-used | verified MIT / requests Apache-2.0 | inspected; safe provider boundary replaces unsafe arbitrary-URL entry |
| other `scripts/`, references, templates, example, assets | same paths | as-is, legacy | verified root MIT | preserved history; no broad functional claims |
| root host instructions / README / pyproject / Makefile / CI | same paths | adapted (planned) | verified root MIT | remove auto-outreach preference; new CLI and blocking offline checks |

New Case models/storage/ingestion/rules/reporting are new code because the upstream lead/outreach artifacts have no persistent inquiry Case schema, rule applicability engine, or inbound-reply contract. Avoiding a new Agent runtime is mandatory.

## Additional audited sources

Each row's license observations derive from the locked root files; details and file hashes are in the P0 supplements.

| Repository / locked SHA | Original | Target | Nature | License / deps | Real test / reason / alternative |
|---|---|---|---|---|---|
| AI_Find_Customer `9b2fde8f719623c627516da2663707a893ee6805` | `backend/tools/url_filter.py` | P2 candidate adapter | not-used until P2 | MIT / stdlib | original tools 80 tests pass; useful classifier, needs hostile-URL fixes |
| AI_Find_Customer same SHA | `contact_extractor.py` | none | not-used | MIT / stdlib | original tests pass; B2B extractor already covers required scope |
| AI_Find_Customer same SHA | PDF parsers / react_runner / agents | none | not-used | root MIT; PDF AGPL/commercial dependencies | excluded; no model loop or extra parsing required |
| crawl4ai `888299fb5f0b82181897dc0e61bfb4b036f0aea5` | HTTP strategy / engine | optional dependency boundary | not-used source | Apache-2.0 plus attribution; 34 dependencies not installed | 4 AST parses pass; runtime blocked until dependency/license audit, static reader alternative |
| web-access `d173a75978ceb2c63fa0b27f7408cd2bf7fe4310` | Skill / CDP Proxy | external optional reference | inspired-only | MIT declaration only, missing full LICENSE; Node 22+ | 6 syntax checks pass; runtime/license blocked; no Proxy copy |
| vibe-seller `c9be95f890108ce6f48cccf66f614c472fbf8ef6` | README isolation approach | browser policy | inspired-only | Apache-2.0 | source inspection only; no GUI/server/mux |
| gpt-researcher `3582a6841fe7dc801e2a34e34ee408641aea9bce` | README research approach | evidence policy | inspired-only | Apache-2.0 | source inspection only; no framework embedded |
| superleads `c45f451ff1846859f22282a444534c67b3034f88` | LICENSE/NOTICE only | exclusion ledger | not-used | PolyForm Noncommercial | no code/templates copied |
| launchfit-ai `99d5a18cdee40bfeb9f117531577c5fdb55d3627` | LICENSE only | exclusion ledger | not-used | PolyForm Noncommercial | no code/templates copied |

## P2 actual migrations and call sites

- AI Hunter `backend/tools/url_filter.py` at `9b2fde8f719623c627516da2663707a893ee6805` → `src/tradecase/vendor/ai_hunter/url_filter.py`: **adapted**, original classifier lists/algorithm retained; HTTP(S), hostname/port and anchored LinkedIn host/path corrections added. Full MIT copyright/license copied next to it and included in package data. No AI Hunter runtime dependencies added. Real integration tests exercise original categories and malicious URL regressions.
- B2B `extract_contacts.normalized_domain` and `FREE_MAIL_DOMAINS` → `assessment.py`: **as-is function reuse**, identity/inquiry domain conflict rules supplement the upstream normalization; no inferred mailbox verification.
- B2B `customs_verify.py`, `evaluate_outreach_drafts.py` → same paths: **adapted import only** for package/CLI coexistence (draft review also removed an unused import). Algorithms retained.
- B2B `send_smtp.py` → same path: **adapted**, network sending code removed from both function and CLI; remaining hashes/validators retained. Legacy implementation recoverable from upstream Git SHA, not an enabled feature.
- `src/tradecase/upstream.py`: wrappers call real inherited extraction/normalization/merge/customs/hash/claim-review functions. P1 14 integration tests and P2 buyer/score tests executed; see phase logs.
- P2 new code supplies Case candidate boundaries, scoring and cross-contract checks absent upstream. It does not duplicate crawler or Agent runtime code.
