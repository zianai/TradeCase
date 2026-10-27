# Upstream audit — P0

Audit date: 2026-10-27. Scope: source inspection and real local execution; no SMTP credentials, paid search keys, login sessions, or external writes used.

## Primary baseline

- Repository: https://github.com/xiongQvQ/-b2b-lead-hunter-skill
- SHA: `ac27d0ec6627366337423bfcb1ba86c5be5a95a5`; complete history preserved locally.
- License: root `LICENSE`, MIT, copyright 2026 xiongbojian. Runtime dependency `requests`; core extract/normalize/dedupe/contracts/customs/draft-review use Python standard library.
- `scripts/`, `references/`, `templates/` retained. No tests directory exists upstream. `_shared/smtp-config.json` is absent; only sample config is present. No real credentials inspected.

## Actual execution

Commands and exact outputs: `docs/evidence/P0/results.json`, `00.log`–`06-serper-no-key.log`.

| Check | Exit | Finding |
|---|---:|---|
| `make check` (Python 3.12.13) | 0 | compile and sender/SMTP sample contracts pass |
| `ruff check scripts/ --no-fix` | 1 | 77 issues, original CI masks this with `|| true` |
| `mypy scripts/ --ignore-missing-imports` | 1 | 14 errors in 5 files |
| README pilot with `example/queries.csv` | 1 | Serper Maps requires a key; no key loaded or paid API called |
| sender-profile sample | 0 | valid |
| pure-function smoke assertions | 0 | extract/normalize/hash/customs exercised; parser and dedupe defects reproduced |

The first lint invocation occurred before local dependency installation completed and raised executable-not-found. It was rerun once installation completed; the table records the completed run. No original source was edited before these runs.

## Code/README differences and boundaries

1. README presents a general pilot. `run_hunt.pilot()` skips organic queries and invokes only Serper Maps; no host-agnostic search execution exists. Keep it as historical tooling, not the V1 entry point.
2. `SKILL.md` contains a personal preference for continuous mining/sending. It is untrusted upstream instruction, incompatible with this project's explicit no-send requirement; replace auto-loaded entry instructions.
3. `normalize_search_results.iter_input()` attempts `json.loads()` on the entire content whenever JSONL begins with `{`, raising on ordinary multi-record JSONL. Wrap `normalize()` with a correct bounded parser.
4. `dedupe_leads.identity()` falls back to name/address. Same-name companies without addresses collide across countries. Reuse normalization and merge helpers only after identity-safe candidate grouping; never merge on name alone.
5. `extract_contacts` labels extracted emails `format_only`. Preserve this; confidence is heuristic, not mailbox verification.
6. `customs_verify.analyze()` can label snippets as confirmed and matches platform strings by substring. Preserve extraction as tentative discovery only; V1 must not promote it to verified evidence or scoring.
7. `read_jina` directly fetches arbitrary URLs and automatically loads an environment key. V1 needs URL/IP/redirect controls and explicit provider choice; no raw private inquiry upload.
8. `send_smtp.send_message()` is a real network write. Disable function and CLI in V1; preserve draft `body_hash`/review separately.
9. Original build backend is `setuptools.backends._legacy:_Backend`; replace with supported `setuptools.build_meta` for the new package, without claiming upstream packaging was tested successfully.

AI Hunter and optional upstream details are stored in the accompanying audit supplements. These findings are implementation evidence, not a blanket legal opinion or certification of all transitive dependencies.
