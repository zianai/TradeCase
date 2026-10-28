# ADR 004: Tenant persistence, durable leases and recoverable deployment

Date: 2026-10-28. Status: implemented; offline and isolated infrastructure checks
executed. This decision does not approve a production deployment or live sending.

## Decisions

The existing filesystem CaseStore and CLI remain intact. The platform's 21
SQLAlchemy tables own tenant business records; old CaseStore materializations are
compatibility views. PostgreSQL is the deployed database; SQLite supports a local
offline demonstration and most CI tests. Alembic revision `20261028_0001` contains
explicit frozen schema operations, not a call to evolving ORM metadata. Tenant
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
- Backend Docker image build was executed using `ops/Dockerfile` and the frozen lock;
  build output is `docs/evidence/full-delivery/docker-backend-build.log`. This build
  validates packaging at the snapshot used by Docker; final integration changes
  require a subsequent build before a release claim.

One observed dependency warning is ARQ 0.28 calling Redis's deprecated `close`
method; it did not fail delivery or cleanup. All stored business data in these
checks is explicitly synthetic. No email, CRM write, paid API call or production
data migration was performed by this work package.
