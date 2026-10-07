#!/usr/bin/env bash
# restore-drill.sh <dump> — restore into a scratch database on the same cluster, verify_chain, compare the
# head with the anchor log, drop the scratch DB. Never touches the live `mbos` database.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; STATE_DIR="$(dirname "$HERE")"
eval "$("$HERE/pg-local.sh" env)"
: "${MBOS_ANCHOR_LOG:=$HOME/.local/share/mbos/anchors/chain-anchors.jsonl}"
: "${MBOS_PY:=$STATE_DIR/.venv/bin/python}"
dump=${1:?usage: restore-drill.sh <mbos-*.dump>}
db=mbos_restore_drill_$(date -u +%Y%m%d%H%M%S)
PSQL=("$PG_BIN/psql" -X -q -v ON_ERROR_STOP=1 -h "$MBOS_PGSOCK" -p "$MBOS_PGPORT")
"${PSQL[@]}" -d postgres -c "CREATE DATABASE $db OWNER mbos_owner TEMPLATE template0"
trap '"${PSQL[@]}" -d postgres -c "DROP DATABASE IF EXISTS $db WITH (FORCE)"' EXIT
"$PG_BIN/pg_restore" -h "$MBOS_PGSOCK" -p "$MBOS_PGPORT" -d "$db" --exit-on-error "$dump"
MBOS_DSN="host=$MBOS_PGSOCK port=$MBOS_PGPORT dbname=$db" PYTHONPATH="$STATE_DIR" \
  "$MBOS_PY" -m mbos_state verify-chain --anchor "$MBOS_ANCHOR_LOG"
echo "restore drill ok ($dump -> $db, dropped after check)"
