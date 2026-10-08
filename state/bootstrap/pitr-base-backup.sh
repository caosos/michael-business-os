#!/usr/bin/env bash
# pitr-base-backup.sh — physical base backup for point-in-time recovery (D-09 part a).
# Needs: MBOS_BACKUP_TARGET (directory). Reads PG_BIN / MBOS_PGSOCK / MBOS_PGPORT like pg-local.sh.
# Connects as the cluster superuser over the local socket (peer auth) unless MBOS_BASEBACKUP_USER is set.
# The backup is self-contained (WAL streamed) and verified with pg_verifybackup before it is reported.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
eval "$("$HERE/pg-local.sh" env)"
: "${MBOS_BACKUP_TARGET:?set MBOS_BACKUP_TARGET (directory)}"
ts=$(date -u +%Y%m%dT%H%M%SZ); dest="$MBOS_BACKUP_TARGET/base/$ts"
mkdir -p "$MBOS_BACKUP_TARGET/base"
user=(); [[ -n "${MBOS_BASEBACKUP_USER:-}" ]] && user=(-U "$MBOS_BASEBACKUP_USER")
"$PG_BIN/pg_basebackup" -h "$MBOS_PGSOCK" -p "$MBOS_PGPORT" "${user[@]}" -D "$dest" -Fp -X stream \
    --checkpoint=fast --label "mbos-$ts" >/dev/null
"$PG_BIN/pg_verifybackup" "$dest" >/dev/null
chmod -R go-rwx "$dest"
echo "$dest"
