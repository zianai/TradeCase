# ADR 004: Tenant persistence, durable leases and recoverable deployment

Date: 2026-10-28. Status: implemented; offline and isolated infrastructure checks
executed. This decision does not approve a production deployment or live sending.

## Decisions

The existing filesystem CaseStore and CLI remain intact. The platform's initial 21
business tables plus a tenant source-cache table own durable records; old CaseStore materializations are
compatibility views. PostgreSQL is the deployed database; SQLite supports a local
offline demonstration and most CI tests. Alembic revision `20261028_0001` contains
explicit frozen schema operations, not a call to evolving ORM metadata. Revision
`20261028_0002` adds the permission-scoped source cache. Tenant
relationships are enforced by composite foreign keys as well as service filters.
Opaque bearer tokens are stored only as hashes. Inquiry original references and
artifact versions reject ORM mutation; service writes create new artifact versions.

TaskManager owns work-unit claims, attempt accounting and retry policy. It never
chooses Case business branches. A unique tenant/Case/type/input-fingerprint key
deduplicates tasks. An atomic database update installs one lease token and increments
the attempt counter; every heartbeat, success and failure must present that live
token. Expired workers cannot publish completion, even if no replacement has claimed
the task. A replacement records the abandoned attempt as LOST. The default lease
clock comes from the database to avoid worker host clock skew. Automatic retries
use bounded exponential delay; explicit retries never exceed ten total attempts.
Human waits release resources and a separately validated decision closes their
work unit. Redis/ARQ delivers wakeups and may deliver a logical task repeatedly.

Local objects use content-addressed paths, integrity checks and atomic installation.
They are shared only by byte identity; authorization is checked against tenant
database references before any fetch. S3Storage implements the same contract with
an injectable boto3 client, server-side encryption and no public ACL. S3 live
credentials and bucket policies have not been verified in this environment. Retention
must account for all database references before deleting shared content.

The Compose stack binds only its web/API ports to loopback (3300/8800 by default).
PostgreSQL and Redis remain private within the stack. Backend and worker run as UID
10001 with the frozen Python lock; the frontend has its separate frozen Node lock.
Default runtime is fake, live model calls are off, and outbound writes are off.
Migration and checkpoint setup happen explicitly before ordinary service startup.
The first concurrent Compose startup exposed a Docker volume copy-up race. The
shared volume now uses `nocopy`; a one-shot initializer prepares only its top-level
directories before either non-root application process starts.

Backup stops the API and workers to make the PostgreSQL dump and object archive
consistent. The dump includes LangGraph checkpoint tables. Restore refuses an
existing Compose project or volume, verifies checksums/archive paths and every
database object reference, and leaves API/worker stopped for operator review.
The initial Alembic downgrade destroys platform data and is only a disposable-test
operation; production release rollback uses a verified backup and matching release.

## Executed evidence

- `tests/platform/test_persistence.py`, `test_tasks.py`, `test_storage.py`:
  schema, tenant foreign keys, immutable originals/versions, migration up/down/up,
  two-worker competition, stale fencing, retry/attempt caps, human task resolution,
  content corruption/traversal/symlinks, and injected S3 protocol checks. The
  recorded command output is in `docs/evidence/full-delivery/persistence-tasks-storage.log`.
- `python ops/verify_infrastructure.py`: creates private labelled temporary
  PostgreSQL 17.6 and Redis 7.4.6 containers and removes its own containers afterward.
  Four real infrastructure tests passed: PostgreSQL Alembic round trip and drift
  check; competing claims and process-independent lease recovery; real ARQ delivery
  through Redis with one Task attempt despite duplicate logical delivery; actual
  `pg_dump`/`pg_restore`, object-reference verification and resumption of an
  interrupted `AsyncPostgresSaver` graph in the restored database.
  Output: `docs/evidence/full-delivery/infrastructure.log`.
- The infrastructure test's socket guard allows only explicitly configured loopback
  test endpoints. It does not remove the existing offline suite's network guard.
- Final backend Docker image build was executed using `ops/Dockerfile` and the
  frozen lock; output is `docs/evidence/full-delivery/docker-release-build.log`.
  Source layers are separate from cached dependencies. Build context excludes
  private environment files, local databases, backups and host dependency folders.
- The built backend was started as a real local non-root container attached to the
  isolated PostgreSQL network. `/api/health` returned HTTP 200 with database=true;
  `docs/evidence/full-delivery/docker-backend-smoke.json` records that result.
  The smoke container was then stopped. This is a runtime/DB smoke, not full GUI E2E.
- The full Compose acceptance then exercised the actual Next.js proxy, API, ARQ
  worker and PostgreSQL. A synthetic Case reached its human approval interrupt in
  12.0 seconds, with five sources, seven claims and three fake Agent runs. The real
  backup/restore scripts copied the database/checkpoints and object archive into a
  separate fresh Compose project; all 22 restored object references verified.
  Approval resumed the same workflow identity to `READY_TO_FOLLOW_UP`, with exactly
  one follow-up, zero external sends and an HTTP 403 default outbound denial.
  The Python source digest matched the host and both running deployments. Elapsed
  time was 137.8 seconds in this local synthetic check, not a production capacity
  benchmark. Evidence: `docs/evidence/full-delivery/compose-acceptance.json` and
  `compose-acceptance.log`. PostgreSQL readiness now uses TCP to exclude its
  temporary initialization socket server before migrations or restores begin.
- Retention's 18 temporary-data tests cover deletion, checkpoint replay, shared
  object references, old reviewed materializations and interrupted review-build
  copies. An independent agent reproduced and verified the repair of the latter
  deletion gaps; current source hashes and scoped findings are recorded in
  `docs/evidence/full-delivery/independent-review-runtime.json`.

One observed dependency warning is ARQ 0.28 calling Redis's deprecated `close`
method; it did not fail delivery or cleanup. All stored business data in these
checks is explicitly synthetic. No email, CRM write, paid API call or production
data migration was performed by this work package.

## Final integrated deployment validation

The final backend was rebuilt from the completed source. Its package SHA-256
matched the host and both original/restored containers. Full Compose acceptance
traversed the Next.js proxy and real API/ARQ/PostgreSQL, persisted a human interrupt,
quiesced and backed up database plus objects, restored into a fresh project,
verified 22 object references and resumed the same workflow to follow-up. The
outbound request was rejected with HTTP403 and no real external writes occurred.
See `docs/evidence/full-delivery/compose-acceptance.json` and its log. The initial
restore probe exposed PostgreSQL's temporary initialization server; readiness now
checks TCP, avoiding the transient Unix-socket-only bootstrap server. Dependency
builds also use bounded downloads and a reusable BuildKit cache after an observed
network timeout. These failures and fixes are recorded, not hidden as success.
