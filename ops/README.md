# Local deployment and recovery

The Compose stack is an isolated TradeCase application: PostgreSQL business and
checkpoint tables, Redis/ARQ, API, worker, Next.js and a shared object volume.
No live model calls or external sends are enabled by this configuration.

1. Install Docker with Compose. From the repository root create a private shell
   environment variable `TRADECASE_DB_PASSWORD` containing a URL-safe password;
   do not commit it. Set `TRADECASE_DEMO_ENABLED=true` for synthetic demonstrations.
2. Run `docker compose -f ops/compose.yaml up --build -d`.
3. Provision an organization/user using the documented platform CLI. User bearer
   tokens are hashed in the database. Keep the CLI's token file private.
4. Open `http://localhost:3300`; API health is `http://localhost:8800/api/health`.
   The database and Redis have no host-published ports. Put an authenticated TLS
   reverse proxy in front before permitting remote users.

Use `uv sync --frozen --extra platform --extra dev` for the exact Python lock.
The backend image uses the same frozen lock. `migrate` runs Alembic and the
official checkpoint saver's setup before the API/worker start. Redis is only a
wakeup channel; persisted task/flow leases and idempotency remain authoritative.
`storage-init` creates the shared object/work directories and sets their ownership
once before application startup. The shared volume disables Docker's automatic
copy-up, avoiding concurrent first-start initialization by API and worker. Only this
short directory preparation runs as root; application processes run as UID 10001.
Changing model runtime or outbound connector settings requires deliberate
deployment configuration and the application's per-action authorization gates.

## Backup and release rollback

`sh ops/backup.sh /absolute/new-backup-directory` briefly stops the API and worker,
captures a custom PostgreSQL dump (including checkpoints), archives objects, hashes
both files, and restarts the services. Store the result encrypted with restricted
access. It includes personal business data. A backup failure intentionally leaves
the application stopped; inspect the error, retain the partial snapshot separately,
and restart only after reconciling the failure.

For a named stack or private environment file, set `TRADECASE_COMPOSE_PROJECT` and
`TRADECASE_COMPOSE_ENV_FILE` when invoking backup. Restore takes its new project
name as an argument and accepts the same environment-file variable. The scripts
create private files (`umask 077`); they do not encrypt the archive themselves.
Encrypt with your organization's approved key-management tooling before transfer
or off-host retention. Never add credential files or business backups to Git.

Restore into a **new Compose project and new volumes**, never over an active
production database: `sh ops/restore.sh /absolute/backup-directory tradecase-restore-unique-name`.
The script refuses existing projects/volumes, validates hashes and archive paths,
restores PostgreSQL and objects, and checks every database object reference.
Run the same locked release, object-reference integrity check,
and checkpoint resume test before moving traffic. Workflow workers must remain
stopped until the restore is validated. Do not copy Redis as a source of task truth;
repair wakeups from database state. Resume a delivery-uncertain outbound action only
after manually reconciling the provider's receipt.

The first Alembic downgrade drops the new platform tables. It is tested only on
disposable databases; it is a destructive rollback, not a production recovery
procedure. Production rollback restores a verified backup and its matching
application release. Keep the old filesystem CLI cases separately; they are not
deleted or migrated automatically.

## Reproducible infrastructure checks

`python ops/verify_infrastructure.py` creates its own labelled PostgreSQL and Redis
containers, executes the opt-in deployment suite, and removes only those created
containers afterward. It never touches other containers or existing named volumes.
The suite checks Alembic up/down, concurrent lease fencing against PostgreSQL,
actual ARQ delivery through Redis, and dump/restore of business data, object refs
and an interrupted LangGraph checkpoint. It uses synthetic test data only.

`ops/compose_acceptance.py` exercises a fresh running Compose deployment through
the Next.js proxy, records a real PostgreSQL/ARQ workflow at its human approval
interrupt, performs the backup/restore scripts into a separate new project and
approves/resumes that same workflow there. It uses fake Agent outputs and synthetic
fixtures; it does not enable real external writes. Its JSON evidence records the
workflow identity, source/object checks, final status and outbound-denial result.
Use `--smoke-only` for a subsequent deployment smoke without backup/restore; its
evidence explicitly records `actual_backup_restore=false`. Both modes compare the
running Python package digest against the local release before exercising it.
The recorded `request_to_review_seconds` timer begins at acceptance startup, so it
includes local operator provisioning and package checks; it is a conservative
end-to-end setup measurement, not isolated workflow latency or a production SLA.
