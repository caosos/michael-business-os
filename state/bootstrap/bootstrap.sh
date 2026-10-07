#!/usr/bin/env bash
# bootstrap.sh — idempotent: roles, databases, passwords, migrations, chain check. Safe to re-run.
# Requires a running cluster reachable as the cluster superuser over the unix socket (pg-local.sh start,
# or the Quadlet container with MBOS_PGSOCK pointing at its mounted socket dir).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="$(dirname "$HERE")"
eval "$("$HERE/pg-local.sh" env)"
: "${MBOS_SECRETS_DIR:=$HOME/.config/mbos/secrets}"
: "${MBOS_PY:=$STATE_DIR/.venv/bin/python}"
PSQL=("$PG_BIN/psql" -X -q -v ON_ERROR_STOP=1 -h "$MBOS_PGSOCK" -p "$MBOS_PGPORT")

echo "== provision (roles, databases, mbos_ext/pgvector, dbos schema, migrations) — mbos_state/provision.py"
PYTHONPATH="$STATE_DIR" "$MBOS_PY" -m mbos_state provision \
  --admin-dsn "host=$MBOS_PGSOCK port=$MBOS_PGPORT dbname=postgres" --app-db mbos --sys-db mbos_dbos --login mbos_dbos

echo "== passwords ($MBOS_SECRETS_DIR, mode 600; never committed)"
mkdir -p "$MBOS_SECRETS_DIR"; chmod 700 "$MBOS_SECRETS_DIR"
PGPASS="$(dirname "$MBOS_SECRETS_DIR")/pgpass"; : > "$PGPASS"; chmod 600 "$PGPASS"
for role in mbos_migrator mbos_reader mbos_state_mcp mbos_gateway mbos_operator_ui mbos_policy mbos_relay mbos_dbos; do
  f="$MBOS_SECRETS_DIR/$role"
  if [[ ! -s "$f" ]]; then
    (umask 077; "$MBOS_PY" -c 'import secrets; print(secrets.token_urlsafe(32))' > "$f")
  fi
  # Password goes through stdin, never argv. token_urlsafe has no quote characters.
  printf "ALTER ROLE %s PASSWORD '%s';\n" "$role" "$(cat "$f")" | "${PSQL[@]}" -d postgres
  echo "127.0.0.1:$MBOS_PGPORT:mbos:$role:$(cat "$f")" >> "$PGPASS"
  # the DBOS login also owns its system database
  [[ $role == mbos_dbos ]] && echo "127.0.0.1:$MBOS_PGPORT:mbos_dbos:$role:$(cat "$f")" >> "$PGPASS"
done

echo "== verify_chain (as mbos_reader over TCP/scram)"
PGPASSFILE="$PGPASS" MBOS_DSN="host=127.0.0.1 port=$MBOS_PGPORT dbname=mbos user=mbos_reader" \
  PYTHONPATH="$STATE_DIR" "$MBOS_PY" -m mbos_state verify-chain
