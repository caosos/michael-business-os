-- roles.sql — cluster-level roles for the MBOS state spine. Idempotent. Run once as a superuser:
--   psql -v ON_ERROR_STOP=1 -d postgres -f state/bootstrap/roles.sql
-- Passwords are NOT set here; bootstrap.sh sets them from files under $MBOS_SECRETS_DIR (never committed).
--
-- Group roles (NOLOGIN) carry privileges; login roles are thin members, one per process, so each
-- credential can be revoked alone (PANIC L1 = revoke one login).

DO $$
DECLARE r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['mbos_owner','agent_read','agent_write','gateway','approver','policy_admin','outbox_relay','owner_channel'] LOOP
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
COMMENT ON ROLE owner_channel IS 'MBOS: Michael''s owner channel — mission, capital, campaigns. Granted ONLY to mbos_operator_ui; never to mbos_dbos/agent_write/gateway/readers (F-80).';
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
        ['mbos_operator_ui', 'owner_channel'],
        ['mbos_policy',      'policy_admin'],
        ['mbos_relay',       'outbox_relay']] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = pair[1]) THEN
            EXECUTE format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS', pair[1]);
        END IF;
        EXECUTE format('GRANT %I TO %I', pair[2], pair[1]);
    END LOOP;
END $$;

-- DBOS app role (ADR-0002; answer to ROUND_TWO_INTEGRATION §3 D). One login for the DBOS process:
--   * owns the DBOS system database `mbos_dbos` (workflow status, queues, durable waits)
--   * owns schema `dbos` inside `mbos`, where DBOS keeps @DBOS.transaction checkpoints
--     (dbos.transaction_outputs) in the SAME transaction as the state write — this is what makes a step
--     and its receipt exactly-once together. bootstrap.sh creates the schema.
--   * writes state ONLY through the mbos.* API with the privileges of agent_write (ingest, items,
--     proposals, outcomes) and gateway (R4 runs 05's gateway/effector in-process, so it settles approved
--     requests). It does NOT hold approver or owner_channel (D-26a): Michael's decisions, notes, capital,
--     campaigns and mission come only from the owner login mbos_operator_ui (approver + owner_channel).
--     RECOMMENDATION: once 05's gateway runs as its own process, revoke gateway from mbos_dbos.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbos_dbos') THEN
        CREATE ROLE mbos_dbos LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    END IF;
END $$;
GRANT agent_write, gateway TO mbos_dbos;
REVOKE approver, owner_channel FROM mbos_dbos;   -- idempotent: clusters provisioned before D-26a had approver
