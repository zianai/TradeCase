# Retention, deletion and evidence integrity

Retention is an explicit administrator operation. It does not run automatically.
Only `CLOSED` Cases older than the chosen UTC cutoff are candidates; planning is
the default. The candidate list contains Case IDs, versions and timestamps, not
raw inquiry text. Administrators are checked against their current active user
record and cannot list or purge another tenant's Cases.

`MaintenanceService.candidates(actor, before)` lists candidates.
`await MaintenanceService.purge(actor, case_id, before=..., expected_version=...,
idempotency_key=..., dry_run=True)` validates the exact Case and returns row counts.
Set `dry_run=False` only after reviewing the plan. The platform CLI exposes these
operations; the service is not an arbitrary SQL or filesystem deletion interface.

A purge rejects active workflows/leases and pending, dispatching or uncertain
outbound actions. Resolve or cancel work and reconcile provider receipts first.
The Case write lock remains held while its stable workflow thread IDs are deleted
using the official checkpoint saver's `adelete_thread`. This deletion is idempotent:
a failed/ambiguous checkpoint deletion rolls back all business deletions; the same
request retries deletion of the same thread IDs. If checkpoints were deleted but
the subsequent database commit failed, retry safely deletes absent threads again.
No Case can be changed concurrently through the service while its lock is held.
The derived compatibility CaseStore directory and every historical
`tenant/review-<version>/case` directory under the configured work root are also
removed under that lock, including Case directories in interrupted
`review-<version>/.review-build-*` staging folders. All candidate paths are validated before deletion and
symlink redirection is rejected; other Cases in the same review directory remain.
These copies can be safely removed again after a partial failure; the
original object-backed business records remain until the database transaction commits.
Legacy CLI cases outside the platform work root are not touched by this operation.

After checkpoint deletion succeeds, the transaction removes Case-owned Agent runs,
attempts, tasks, source/claim links, artifacts and versions, approvals, outbound
records, findings, assessments, follow-ups, events, audits, workflows and the Case.
Inquiry and buyer records are removed only when no other Case references them.
A minimal audit remains with `case_id=NULL`, actor ID, a hash of tenant/Case ID,
counts, timestamp and the purge idempotency key. It contains no draft, inquiry,
source excerpt, address, receipt or snapshot path. Repeating the same successful
purge key returns the prior result; reusing it for another Case fails.

## Object bytes require a separate garbage-collection step

Database purge **does not by itself physically erase all retained bytes**. Content
objects may be shared by multiple Cases or tenants. `object_gc_required=true`
explicitly signals this distinction. Backups, external provider copies, OS storage
snapshots and audit/account retention also have their own retention policies.

`MaintenanceService.gc_orphans()` is an operator-only local-storage inventory with
a seven-day grace period, and defaults to dry-run. It recursively scans exact
content references in all business database fields across **all tenants**, including
task/Agent JSON outputs. It never deletes a still-referenced shared blob. The final
physical step requires `dry_run=False, quiesced=True`: stop every API process,
worker, importer and other object writer first. An online reference scan cannot
exclude a writer between content `put()` and database commit. The method refuses
deletion without that explicit quiescence assertion and rechecks references before
unlinking. Keep it out of tenant HTTP routes. Do not shorten the grace period for
normal operations merely because tests use zero age on disposable synthetic data.

S3 orphan deletion is deliberately unsupported by this local GC method; use a
separately reviewed bucket inventory and lifecycle policy with the same reference,
quiescence and retention safeguards. Bucket versions/replicas and encrypted backups
must be handled explicitly. No claim of regulatory erasure is implied by the
application returning PURGED.

Expired source-cache entries still protect their object references until explicitly
pruned. `MaintenanceService.prune_expired_cache(actor)` defaults to dry-run; its
explicit execution deletes only that administrator's expired cache rows with no
live fetch lease, and never directly deletes object bytes. Other Case, Agent or
organization knowledge references continue to protect a shared object. Knowledge
documents require their separate approved lifecycle; Case purge does not remove
an organization's shared knowledge library.

## Integrity and executed tests

`MaintenanceService.verify_objects(actor)` checks original inquiries, source
snapshots, artifacts and cache/knowledge/Agent/task object references for one tenant
and reports only row IDs/error codes.
`python ops/verify_object_references.py` is the read-only global restore check for
operators. Neither returns the underlying private bytes.

The retention tests use temporary synthetic databases and local objects. They cover
default dry-run, tenant/admin/version/cutoff checks, active-work refusal, ambiguous
checkpoint failure and replay, real SQLite checkpoint deletion, cross-tenant shared
object protection, task JSON references, corruption detection and explicit offline
GC. No existing user Case or production storage was purged during development.
