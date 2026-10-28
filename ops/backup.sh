#!/bin/sh
# Stop workers/API first for an application-consistent DB + object snapshot.
# Does not delete data or print credentials. Keep the backup private.
set -eu
umask 077
if [ "$#" -ne 1 ]; then
  echo 'Usage: sh ops/backup.sh /absolute/new-backup-directory' >&2
  exit 2
fi
backup_dir=$1
case "$backup_dir" in /*) ;; *) echo 'Backup path must be absolute' >&2; exit 2;; esac
if [ -e "$backup_dir" ]; then echo 'Backup destination must not exist' >&2; exit 2; fi
mkdir -m 700 "$backup_dir"
compose_file=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/compose.yaml
compose() {
  if [ -n "${TRADECASE_COMPOSE_ENV_FILE:-}" ]; then
    docker compose --env-file "$TRADECASE_COMPOSE_ENV_FILE" -p "${TRADECASE_COMPOSE_PROJECT:-tradecase}" -f "$compose_file" "$@"
  else
    docker compose -p "${TRADECASE_COMPOSE_PROJECT:-tradecase}" -f "$compose_file" "$@"
  fi
}
compose stop api worker
compose exec -T postgres pg_dump -U tradecase -d tradecase --format=custom --no-owner > "$backup_dir/database.dump"
compose run --rm --no-deps -T --entrypoint tar api -C /app/.tradecase -czf - objects > "$backup_dir/objects.tar.gz"
python3 - "$backup_dir" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.iterdir()) if p.is_file()}
(root / 'sha256.json').write_text(json.dumps(manifest, indent=2) + '\n')
PY
compose start api worker
echo 'Backup created. The dump includes business records and LangGraph checkpoints.'
