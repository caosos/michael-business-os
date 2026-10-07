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

echo "== roles"
"${PSQL[@]}" -d postgres -f "$HERE/roles.sql"

echo "== databases"
for spec in mbos:mbos_owner mbos_dbos:mbos_dbos; do
  db=${spec%%:*}; owner=${spec##*:}
  if [[ -z "$("${PSQL[@]}" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$db'")" ]]; then
    "${PSQL[@]}" -d postgres -c "CREATE DATABASE $db OWNER $owner ENCODING 'UTF8' TEMPLATE template0"
  fi
done
"${PSQL[@]}" -d postgres <<SQL
REVOKE ALL ON DATABASE mbos FROM PUBLIC;
GRANT CONNECT ON DATABASE mbos TO agent_read, agent_write, gateway, approver, policy_admin, outbox_relay, mbos_migrator;
REVOKE ALL ON DATABASE mbos_dbos FROM PUBLIC;
SQL
"${PSQL[@]}" -d mbos -c "REVOKE ALL ON SCHEMA public FROM PUBLIC"
# DBOS @DBOS.transaction checkpoints live in schema dbos of the app DB (same txn as the state write).
"${PSQL[@]}" -d mbos -c "CREATE SCHEMA IF NOT EXISTS dbos AUTHORIZATION mbos_dbos"
"${PSQL[@]}" -d postgres -c "GRANT CONNECT ON DATABASE mbos TO mbos_dbos"

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
  db=mbos; [[ $role == mbos_dbos ]] && db=mbos_dbos
  echo "127.0.0.1:$MBOS_PGPORT:$db:$role:$(cat "$f")" >> "$PGPASS"
done

echo "== migrations"
MBOS_ADMIN_DSN="host=$MBOS_PGSOCK port=$MBOS_PGPORT dbname=mbos" \
  PYTHONPATH="$STATE_DIR" "$MBOS_PY" -m mbos_state migrate

echo "== verify_chain (as mbos_reader over TCP/scram)"
PGPASSFILE="$PGPASS" MBOS_DSN="host=127.0.0.1 port=$MBOS_PGPORT dbname=mbos user=mbos_reader" \
  PYTHONPATH="$STATE_DIR" "$MBOS_PY" -m mbos_state verify-chain
