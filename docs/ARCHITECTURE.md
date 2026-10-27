# Architecture

The existing host Agent owns searching, reasoning and the execution loop. Shared
Skills describe evidence and stop conditions. Python owns contracts, persistence,
normalization, scoring, rule applicability and rendering. There is no model client,
Agent loop, frontend, HTTP service, worker queue or scheduler.

`CaseStore` is a single-writer JSON/JSONL store guarded by a local file lock. A
revision stages validated after-images in `.transaction.json`, atomically replaces
each artifact and commits `manifest.json` last. `recover` replays an interrupted
journal idempotently. Previous artifact bytes are kept in `.history/<revision>/`.
A partial transaction must be recovered before new changes. Completed/cancelled
Cases require an explicit transition back to running before edits. This is an
audit mechanism, not protection against an adversarial shell user.

`input.json` keeps readable raw content, original bytes in Base64 and SHA256, so
non-UTF-8 mail remains recoverable. Attachments are metadata only and are not run.
Case identifiers, UTC timestamps and schema version are checked. Markdown is a
view; JSON/JSONL are business records. The validator checks references and hashes,
not the truth of arbitrary natural language.

Optional networking accepts only approved public HTTP(S) destinations; all pages
are untrusted. Installed browser providers require separate authorization and
license clearance. Missing tools do not block offline cases.
