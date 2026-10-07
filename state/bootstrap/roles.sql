-- roles.sql — cluster-level roles for the MBOS state spine. Idempotent. Run once as a superuser:
--   psql -v ON_ERROR_STOP=1 -d postgres -f state/bootstrap/roles.sql
-- Passwords are NOT set here; bootstrap.sh sets them from files under $MBOS_SECRETS_DIR (never committed).
--
-- Group roles (NOLOGIN) carry privileges; login roles are thin members, one per process, so each
-- credential can be revoked alone (PANIC L1 = revoke one login).

DO $$
DECLARE r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['mbos_owner','agent_read','agent_write','gateway','approver','policy_admin','outbox_relay'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS', r);
        END IF;
    END LOOP;
END $$;

COMMENT ON ROLE mbos_owner   IS 'MBOS: owns schema objects; used only by migrations (SET ROLE). Append-only triggers still apply.';
COMMENT ON ROLE agent_read   IS 'MBOS: read-only (read tools, reporting, backups verification).';
COMMENT ON ROLE agent_write  IS 'MBOS: State MCP server — items, proposals, outcomes, lessons. Cannot approve, execute or spend.';
COMMENT ON ROLE gateway      IS 'MBOS: Action Gateway (05) — classify, execute, budget. Cannot approve.';
COMMENT ON ROLE approver     IS 'MBOS: Operator UI backend — records Michael''s YES/NO/MODIFY/HOLD. Cannot execute or spend.';
COMMENT ON ROLE policy_admin IS 'MBOS: governance policy versions (human-initiated).';
COMMENT ON ROLE outbox_relay IS 'MBOS: outbox delivery bookkeeping only.';

DO $$
DECLARE pair text[];
BEGIN
    FOREACH pair SLICE 1 IN ARRAY ARRAY[
        ['mbos_migrator',    'mbos_owner'],
        ['mbos_reader',      'agent_read'],
        ['mbos_state_mcp',   'agent_write'],
        ['mbos_gateway',     'gateway'],
        ['mbos_operator_ui', 'approver'],
        ['mbos_policy',      'policy_admin'],
        ['mbos_relay',       'outbox_relay']] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = pair[1]) THEN
            EXECUTE format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS', pair[1]);
        END IF;
        EXECUTE format('GRANT %I TO %I', pair[2], pair[1]);
    END LOOP;
END $$;

-- DBOS system database role (ADR-0002). DBOS owns workflow durability in its own database; the state
-- spine never stores workflow positions. Agent 01 decides whether the DBOS app reuses this role.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbos_dbos') THEN
        CREATE ROLE mbos_dbos LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    END IF;
END $$;
