#!/bin/sh
# Nightly backup of the Postgres database and the uploaded bills. Safe to run from cron: it moves to the repository folder itself, and the files it writes are private to the owner.
#   BACKUP_DIR       where the files go (default /var/backups/booklantern)
#   BACKUP_COPY_TO   optional rsync target on ANOTHER machine, for example user@host:/backups/booklantern/ (a copy on the same disk is not a backup)
set -eu
umask 077  # bills, bank lines and the audit log must not be readable by other users of this server
cd "$(dirname "$0")/../.."
OUT="${BACKUP_DIR:-/var/backups/booklantern}"
mkdir -p "$OUT"
STAMP=$(date +%Y%m%d-%H%M)
DUMP="$OUT/booklantern-$STAMP.dump"
FILES="$OUT/uploads-$STAMP.tar"
TMP_DUMP="$DUMP.partial"
TMP_FILES="$FILES.partial"
trap 'rm -f -- "$TMP_DUMP" "$TMP_FILES"' EXIT
# Write to a partial file first, so a failed dump never counts as a backup and never pushes a good one out of the rotation.
docker compose exec -T db pg_dump -U booklantern -Fc booklantern > "$TMP_DUMP"
if [ ! -s "$TMP_DUMP" ]; then
  echo "backup failed: the database dump is empty" >&2
  exit 1
fi
mv -- "$TMP_DUMP" "$DUMP"
docker compose exec -T api tar -C /data -cf - uploads > "$TMP_FILES" || true
if [ -s "$TMP_FILES" ]; then mv -- "$TMP_FILES" "$FILES"; fi
# keep the newest 14 of each
ls -1t "$OUT"/booklantern-*.dump | tail -n +15 | while read -r old; do rm -f -- "$old"; done
ls -1t "$OUT"/uploads-*.tar 2>/dev/null | tail -n +15 | while read -r old; do rm -f -- "$old"; done
if [ -n "${BACKUP_COPY_TO:-}" ]; then
  rsync -a "$OUT"/ "$BACKUP_COPY_TO"
  echo "copied to $BACKUP_COPY_TO"
fi
echo "wrote $DUMP"
