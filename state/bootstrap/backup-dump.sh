#!/usr/bin/env bash
# backup-dump.sh — nightly logical backup (complements pgBackRest PITR, which lands with off-box storage).
# Writes: mbos-<ts>.dump (pg_dump -Fc), chain-<ts>.jsonl (offline-verifiable receipt chain), and appends
# the head to the anchor log. Copy $MBOS_BACKUP_DIR off-box (3-2-1).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; STATE_DIR="$(dirname "$HERE")"
eval "$("$HERE/pg-local.sh" env)"
: "${MBOS_BACKUP_DIR:=$HOME/.local/share/mbos/backups}"
: "${MBOS_ANCHOR_LOG:=$HOME/.local/share/mbos/anchors/chain-anchors.jsonl}"
: "${MBOS_PY:=$STATE_DIR/.venv/bin/python}"
ts=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$MBOS_BACKUP_DIR" "$(dirname "$MBOS_ANCHOR_LOG")"; chmod 700 "$MBOS_BACKUP_DIR"
"$PG_BIN/pg_dump" -h "$MBOS_PGSOCK" -p "$MBOS_PGPORT" -d mbos -Fc -f "$MBOS_BACKUP_DIR/mbos-$ts.dump"
export MBOS_DSN="host=$MBOS_PGSOCK port=$MBOS_PGPORT dbname=mbos" PYTHONPATH="$STATE_DIR"
"$MBOS_PY" -m mbos_state export-chain --out "$MBOS_BACKUP_DIR/chain-$ts.jsonl"
"$MBOS_PY" -m mbos_state anchor --out "$MBOS_ANCHOR_LOG"
"$MBOS_PY" -m mbos_state verify-export "$MBOS_BACKUP_DIR/chain-$ts.jsonl" --anchor "$MBOS_ANCHOR_LOG"
sha256sum "$MBOS_BACKUP_DIR/mbos-$ts.dump" "$MBOS_BACKUP_DIR/chain-$ts.jsonl" > "$MBOS_BACKUP_DIR/SHA256SUMS-$ts"
echo "backup $ts ok"
