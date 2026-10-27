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
