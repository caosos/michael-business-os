#!/usr/bin/env bash
# pg-local.sh — wave-one, user-space PostgreSQL 16 cluster for the MBOS state spine (no root, no Podman).
# usage: pg-local.sh init|enable-archive|start|stop|status|env
#
# Isolation from anything else on the host (e.g. CAOSCare): own data dir, own port (55432), own socket dir,
# loopback only. It never touches a system cluster or port 5432.
#
# Binaries: $PG_BIN, else PGDG /usr/lib/postgresql/16/bin, else the pgserver wheel in state/.venv.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="$(dirname "$HERE")"
: "${MBOS_HOME:=$HOME/.local/share/mbos}"
: "${MBOS_PGDATA:=$MBOS_HOME/pg16}"
: "${MBOS_PGSOCK:=$MBOS_HOME/run}"
: "${MBOS_PGPORT:=55432}"

find_bin() {
  if [[ -n "${PG_BIN:-}" ]]; then echo "$PG_BIN"; return; fi
  if [[ -x /usr/lib/postgresql/16/bin/pg_ctl ]]; then echo /usr/lib/postgresql/16/bin; return; fi
  local w
  w=$(ls -d "$STATE_DIR"/.venv/lib/python3*/site-packages/pgserver/pginstall/bin 2>/dev/null | head -1 || true)
  if [[ -n "$w" ]]; then echo "$w"; return; fi
  echo "error: no PostgreSQL 16 binaries (set PG_BIN, install postgresql-16, or 'pip install pgserver' in state/.venv)" >&2
  exit 2
}
PG_BIN="$(find_bin)"

case "${1:-}" in
  init)
    if [[ -f "$MBOS_PGDATA/PG_VERSION" ]]; then echo "cluster exists at $MBOS_PGDATA"; exit 0; fi
    mkdir -p "$MBOS_PGDATA" "$MBOS_PGSOCK"; chmod 700 "$MBOS_PGDATA" "$MBOS_PGSOCK"
    "$PG_BIN/initdb" -D "$MBOS_PGDATA" --encoding=UTF8 --locale=C.UTF-8 --data-checksums \
        --auth-local=peer --auth-host=scram-sha-256 >/dev/null
    cat >> "$MBOS_PGDATA/postgresql.conf" <<CONF

# --- MBOS state spine (agent 04) ---
listen_addresses = '127.0.0.1'
port = $MBOS_PGPORT
unix_socket_directories = '$MBOS_PGSOCK'
password_encryption = 'scram-sha-256'
wal_level = replica              # pgBackRest / PITR ready (archive_command set when pgBackRest lands)
synchronous_commit = on          # a committed receipt is durable
full_page_writes = on
fsync = on
log_destination = 'stderr'
logging_collector = on
log_directory = 'log'
log_min_duration_statement = 1000
log_line_prefix = '%m [%p] %q%u@%d '
timezone = 'UTC'
CONF
    if [[ -n "${MBOS_WAL_ARCHIVE:-}" ]]; then   # continuous archiving for PITR (D-09): destination is one directory
      cat >> "$MBOS_PGDATA/postgresql.conf" <<CONF
archive_mode = on
archive_timeout = 300                # force a segment at least every 5 min => bounds the loss window
archive_command = '$HERE/archive-wal.sh $MBOS_WAL_ARCHIVE %p %f'
CONF
    fi
    echo "initialized $MBOS_PGDATA (port $MBOS_PGPORT, socket $MBOS_PGSOCK)"
    ;;
  enable-archive)   # existing cluster: needs MBOS_WAL_ARCHIVE; restart required for archive_mode
    : "${MBOS_WAL_ARCHIVE:?set MBOS_WAL_ARCHIVE (directory)}"
    grep -q '^archive_mode = on' "$MBOS_PGDATA/postgresql.conf" && { echo "archiving already enabled"; exit 0; }
    cat >> "$MBOS_PGDATA/postgresql.conf" <<CONF

# --- continuous archiving (D-09) ---
archive_mode = on
archive_timeout = 300
archive_command = '$HERE/archive-wal.sh $MBOS_WAL_ARCHIVE %p %f'
CONF
    echo "archiving enabled -> $MBOS_WAL_ARCHIVE (restart the cluster to apply)" ;;
  start)
    "$PG_BIN/pg_ctl" -D "$MBOS_PGDATA" -l "$MBOS_HOME/postgres.log" -w start ;;
  start-foreground)   # for systemd (Type=simple)
    exec "$PG_BIN/postgres" -D "$MBOS_PGDATA" ;;
  stop)
    "$PG_BIN/pg_ctl" -D "$MBOS_PGDATA" -m fast -w stop ;;
  status)
    "$PG_BIN/pg_ctl" -D "$MBOS_PGDATA" status ;;
  env)
    echo "export PG_BIN=$PG_BIN MBOS_PGDATA=$MBOS_PGDATA MBOS_PGSOCK=$MBOS_PGSOCK MBOS_PGPORT=$MBOS_PGPORT" ;;
  *)
    echo "usage: $0 init|enable-archive|start|start-foreground|stop|status|env" >&2; exit 2 ;;
esac
