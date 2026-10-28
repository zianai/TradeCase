#!/bin/sh
# Restore only into a new Compose project. Does not start application traffic.
set -eu
umask 077
if [ "$#" -ne 2 ]; then
  echo 'Usage: sh ops/restore.sh /absolute/backup-directory tradecase-restore-unique-name' >&2
  exit 2
fi
backup_dir=$1
restore_project=$2
case "$backup_dir" in /*) ;; *) echo 'Backup path must be absolute' >&2; exit 2;; esac
case "$restore_project" in tradecase-restore-*) ;; *) echo 'Project must start tradecase-restore-' >&2; exit 2;; esac
case "$restore_project" in *[!a-z0-9-]*) echo 'Project name may use lowercase letters, digits and hyphens only' >&2; exit 2;; esac
compose_file=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/compose.yaml
compose() {
  if [ -n "${TRADECASE_COMPOSE_ENV_FILE:-}" ]; then
    docker compose --env-file "$TRADECASE_COMPOSE_ENV_FILE" -p "$restore_project" -f "$compose_file" "$@"
  else
    docker compose -p "$restore_project" -f "$compose_file" "$@"
  fi
}
if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$restore_project")" ] || \
   [ -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$restore_project")" ]; then
  echo 'Refusing to replace an existing project or volume' >&2
  exit 2
fi
python3 - "$backup_dir" <<'PY'
import hashlib, json, pathlib, sys, tarfile
root = pathlib.Path(sys.argv[1])
manifest = json.loads((root / 'sha256.json').read_text())
for name in ('database.dump', 'objects.tar.gz'):
    if hashlib.sha256((root / name).read_bytes()).hexdigest() != manifest[name]:
        raise SystemExit('Backup checksum mismatch')
with tarfile.open(root / 'objects.tar.gz') as archive:
    for member in archive:
        path = pathlib.PurePosixPath(member.name)
        if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != 'objects':
            raise SystemExit('Unsafe backup archive path')
        if not member.isfile() and not member.isdir():
            raise SystemExit('Backup must contain regular files and directories only')
PY
compose up -d --wait postgres redis
compose exec -T postgres pg_restore -U tradecase -d tradecase --no-owner --exit-on-error < "$backup_dir/database.dump"
compose build api
compose run --rm --no-deps -T storage-init
compose run --rm --no-deps -T --entrypoint tar api -C /app/.tradecase -xzf - < "$backup_dir/objects.tar.gz"
compose run --rm --no-deps -T --entrypoint python api ops/verify_object_references.py
echo 'Restore integrity checked in the new project. API and worker remain stopped for checkpoint and receipt review.'
