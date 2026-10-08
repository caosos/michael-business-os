#!/usr/bin/env bash
# restore-pitr.sh — restore a base backup + archived WAL into a NEW data directory and start it (D-09 part a).
#   restore-pitr.sh --base DIR --archive DIR --data DIR --port N --sock DIR  (--target-name NAME | --target-time TS | --latest)
# Never touches the live cluster. The restored cluster does NOT archive (archive_mode=off), so it cannot write
# into the archive it was restored from. Recovery must REACH the target: if the WAL needed is missing or damaged
# PostgreSQL refuses to open (FATAL) instead of silently promoting a shorter history, and this script exits non-zero.
set -euo pipefail
base= archive= data= port= sock= mode= target=
while [[ $# -gt 0 ]]; do case $1 in
  --base) base=$2; shift 2;; --archive) archive=$2; shift 2;; --data) data=$2; shift 2;;
  --port) port=$2; shift 2;; --sock) sock=$2; shift 2;;
  --target-name) mode=name; target=$2; shift 2;; --target-time) mode=time; target=$2; shift 2;;
  --latest) mode=latest; shift;; *) echo "unknown arg $1" >&2; exit 2;; esac; done
for v in base archive data port sock mode; do [[ -n "${!v}" ]] || { echo "missing --${v//_/-}" >&2; exit 2; }; done
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
eval "$("$HERE/pg-local.sh" env)"
[[ -e "$data" ]] && { echo "refusing: $data already exists" >&2; exit 2; }
mkdir -p "$sock"; chmod 700 "$sock"
cp -a "$base" "$data"; chmod 700 "$data"
rm -f "$data/postmaster.pid" "$data/recovery.signal" "$data/standby.signal"
{
  echo "# --- written by restore-pitr.sh ---"
  echo "archive_mode = off"
  # cat, not cp: archived segments are read-only (0440) and cp would preserve that, but recovery must write them.
  # Exits non-zero when the file is absent, which is how PostgreSQL learns the archive has ended.
  echo "restore_command = 'cat \"$archive/%f\" > \"%p\"'"
  case $mode in
    name)   echo "recovery_target_name = '$target'";;
    time)   echo "recovery_target_time = '$target'";;
  esac
  echo "recovery_target_action = 'promote'"
  echo "port = $port"
  echo "unix_socket_directories = '$sock'"
  echo "listen_addresses = ''"
} >> "$data/postgresql.auto.conf"
touch "$data/recovery.signal"
if ! "$PG_BIN/pg_ctl" -D "$data" -l "$data/restore.log" -w -t "${MBOS_RESTORE_TIMEOUT:-60}" start >/dev/null; then
  echo "restore FAILED (see $data/restore.log):" >&2; tail -5 "$data/restore.log" >&2; exit 1
fi
user=(); [[ -n "${MBOS_BASEBACKUP_USER:-}" ]] && user=(-U "$MBOS_BASEBACKUP_USER")   # default: the OS user = cluster superuser
for _ in $(seq 1 120); do   # pg_ctl -w returns once connections are accepted; wait for promotion to finish
  if ! "$PG_BIN/pg_ctl" -D "$data" status >/dev/null 2>&1; then break; fi          # server died during recovery
  [[ "$("$PG_BIN/psql" -X -Atq -h "$sock" -p "$port" "${user[@]}" -d postgres -c 'SELECT pg_is_in_recovery()' 2>/dev/null)" == "f" ]] \
    && { echo "restored: $data (port $port, socket $sock)"; exit 0; }
  sleep 0.5
done
echo "restore FAILED: recovery did not finish (see $data/restore.log):" >&2; tail -5 "$data/restore.log" >&2; exit 1
