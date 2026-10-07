#!/usr/bin/env bash
# restore-drill.sh <dump> — restore into a scratch database on the same cluster, verify_chain, compare the
# head with the anchor log, drop the scratch DB. Never touches the live `mbos` database.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; STATE_DIR="$(dirname "$HERE")"
eval "$("$HERE/pg-local.sh" env)"
: "${MBOS_ANCHOR_LOG:=$HOME/.local/share/mbos/anchors/chain-anchors.jsonl}"
: "${MBOS_PY:=$STATE_DIR/.venv/bin/python}"
fresh=0
if [[ "${1:-}" == "--fresh-cluster" ]]; then fresh=1; shift; fi
dump=${1:?usage: restore-drill.sh [--fresh-cluster] <mbos-*.dump>}

if [[ $fresh == 1 ]]; then
  # D1: restore into a brand-new cluster (own initdb, port, socket; roles bootstrapped from scratch).
  # Closest stand-in for a fresh host available here; the procedure is identical on a second machine.
  work=$(mktemp -d); sock=$(mktemp -d "${XDG_RUNTIME_DIR:-/tmp}/mbos-drill.XXXX"); port=${MBOS_DRILL_PORT:-55498}
  cleanup() { "$PG_BIN/pg_ctl" -D "$work/data" -m fast -w stop >/dev/null 2>&1 || true; rm -rf "$work" "$sock"; }
  trap cleanup EXIT
  "$PG_BIN/initdb" -D "$work/data" --auth=trust -U postgres --encoding=UTF8 --locale=C.UTF-8 --data-checksums >/dev/null
  "$PG_BIN/pg_ctl" -D "$work/data" -l "$work/pg.log" -w start -o "-p $port -k $sock -c listen_addresses='' -c timezone=UTC" >/dev/null
  P=("$PG_BIN/psql" -X -q -v ON_ERROR_STOP=1 -h "$sock" -p "$port" -U postgres)
  "${P[@]}" -d postgres -f "$HERE/roles.sql"
  "${P[@]}" -d postgres -c "CREATE DATABASE mbos OWNER mbos_owner TEMPLATE template0"
  "$PG_BIN/pg_restore" -h "$sock" -p "$port" -U postgres -d mbos --exit-on-error "$dump"
  export MBOS_DSN="host=$sock port=$port dbname=mbos user=mbos_reader" PYTHONPATH="$STATE_DIR"
  "$MBOS_PY" -m mbos_state verify-chain --anchor "$MBOS_ANCHOR_LOG"
  "$MBOS_PY" -m mbos_state export-chain --out "$work/chain.jsonl"
  "$MBOS_PY" -m mbos_state verify-export "$work/chain.jsonl" --anchor "$MBOS_ANCHOR_LOG"
  "$MBOS_PY" -c "import json,sys; sys.path.insert(0,'$STATE_DIR/mbos_state'); import mbos_canonical as m; \
print('ADR-0010 reference verify_chain:', m.verify_chain([json.loads(l) for l in open('$work/chain.jsonl')]))"
  echo "fresh-cluster restore drill ok ($dump -> new cluster on port $port, torn down)"
  exit 0
fi

db=mbos_restore_drill_$(date -u +%Y%m%d%H%M%S)
PSQL=("$PG_BIN/psql" -X -q -v ON_ERROR_STOP=1 -h "$MBOS_PGSOCK" -p "$MBOS_PGPORT")
"${PSQL[@]}" -d postgres -c "CREATE DATABASE $db OWNER mbos_owner TEMPLATE template0"
trap '"${PSQL[@]}" -d postgres -c "DROP DATABASE IF EXISTS $db WITH (FORCE)"' EXIT
"$PG_BIN/pg_restore" -h "$MBOS_PGSOCK" -p "$MBOS_PGPORT" -d "$db" --exit-on-error "$dump"
MBOS_DSN="host=$MBOS_PGSOCK port=$MBOS_PGPORT dbname=$db" PYTHONPATH="$STATE_DIR" \
  "$MBOS_PY" -m mbos_state verify-chain --anchor "$MBOS_ANCHOR_LOG"
echo "restore drill ok ($dump -> $db, dropped after check)"
