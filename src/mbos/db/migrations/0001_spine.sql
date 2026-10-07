-- 0001_spine.sql — Michael Business OS durable spine (contracts v1.0.0, ADR-0001/0004/0005)
--
-- Ownership: Agent 01 wrote this as the REFERENCE spine so the A1–A10 suite can run.
-- Agent 04 (State lane) owns DDL going forward: extend or supersede it with numbered
-- migrations (0002_*.sql …). Never edit an applied migration; the migrator checks hashes.
--
-- Invariants enforced IN THE DATABASE (not only in Python):
--   * receipts / approvals / provenance / outcomes / artifacts / effector_calls are insert-only (A2)
--   * receipts form a sha256 hash chain ordered by seq, assigned under one lock (A3)
--   * every receipt cites >= 1 provenance id that exists (A4: "no receipt without provenance")
--   * every effector receipt and effector call is dry_run = true during the MVP (A7)
--   * Item state changes follow the ADR-0004 state machine
--   * an ActionRequest's payload is frozen once proposed
--   * an Approval must have seen the request's exact payload_hash

CREATE SCHEMA IF NOT EXISTS mbos;
SET LOCAL search_path = mbos, public;

-- ---------------------------------------------------------------- roles
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_read') THEN CREATE ROLE agent_read NOLOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_write') THEN CREATE ROLE agent_write NOLOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gateway') THEN CREATE ROLE gateway NOLOGIN; END IF;
END $$;

-- ---------------------------------------------------------------- shared guards
CREATE OR REPLACE FUNCTION mbos.reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'mbos: % on %.% is forbidden (insert-only ledger)', TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME
        USING ERRCODE = 'insufficient_privilege';
END $$;

CREATE OR REPLACE FUNCTION mbos.make_insert_only(tbl regclass) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %s FOR EACH ROW EXECUTE FUNCTION mbos.reject_mutation()',
                   'insert_only_row', tbl);
    EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON %s FOR EACH STATEMENT EXECUTE FUNCTION mbos.reject_mutation()',
                   'insert_only_truncate', tbl);
END $$;

-- ---------------------------------------------------------------- provenance
CREATE TABLE mbos.provenance (
    seq           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provenance_id text GENERATED ALWAYS AS (body->>'provenance_id') STORED UNIQUE NOT NULL,
    body          jsonb NOT NULL,
    CHECK (body->>'provenance_id' ~ '^prov_[0-9A-HJKMNP-TV-Z]{26}$'),
    -- anyOf rule from provenance.schema.json (A4)
    CHECK ((body ? 'source_uri' AND body ? 'fetched_at')
        OR (body ? 'model_id' AND body ? 'model_version' AND body ? 'prompt_hash')
        OR (body ? 'approval_id')
        OR (body ? 'tool_name' AND body ? 'tool_version'))
);
SELECT mbos.make_insert_only('mbos.provenance');

-- ---------------------------------------------------------------- artifacts (content-addressed; 04 moves to FS/Garage)
CREATE TABLE mbos.artifacts (
    sha256      text PRIMARY KEY CHECK (sha256 ~ '^sha256:[0-9a-f]{64}$'),
    media_type  text NOT NULL,
    content     bytea NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CHECK (sha256 = 'sha256:' || encode(pg_catalog.sha256(content), 'hex'))
);
SELECT mbos.make_insert_only('mbos.artifacts');

-- ---------------------------------------------------------------- items (current state; history = receipts)
CREATE TABLE mbos.items (
    item_id     text GENERATED ALWAYS AS (body->>'item_id') STORED PRIMARY KEY,
    type        text GENERATED ALWAYS AS (body->>'type') STORED NOT NULL,
    category    text GENERATED ALWAYS AS (body->>'category') STORED NOT NULL,
    state       text GENERATED ALWAYS AS (body->>'state') STORED NOT NULL,
    dedup_key   text GENERATED ALWAYS AS (body->>'dedup_key') STORED NOT NULL UNIQUE,
    version     integer NOT NULL DEFAULT 1,
    body        jsonb NOT NULL,
    CHECK (body->>'item_id' ~ '^itm_[0-9A-HJKMNP-TV-Z]{26}$')
);
CREATE INDEX items_state_idx ON mbos.items (state);

CREATE TABLE mbos.item_state_transitions (
    from_state text NOT NULL,
    to_state   text NOT NULL,
    PRIMARY KEY (from_state, to_state)
);
INSERT INTO mbos.item_state_transitions (from_state, to_state) VALUES
    ('DISCOVERED', 'NORMALIZED'),
    ('NORMALIZED', 'RESEARCHING'), ('NORMALIZED', 'SCORED'),
    ('RESEARCHING', 'SCORED'), ('SCORED', 'RESEARCHING'),
    ('SCORED', 'RECOMMENDED'),
    ('RECOMMENDED', 'AWAITING_APPROVAL'), ('RECOMMENDED', 'RESEARCHING'),
    ('AWAITING_APPROVAL', 'APPROVED'), ('AWAITING_APPROVAL', 'HELD'), ('AWAITING_APPROVAL', 'REJECTED'),
    ('HELD', 'AWAITING_APPROVAL'), ('HELD', 'APPROVED'), ('HELD', 'REJECTED'),
    ('APPROVED', 'ACTING'), ('ACTING', 'ACTED'),
    ('ACTED', 'OUTCOME_RECORDED'), ('OUTCOME_RECORDED', 'LEARNED');
-- ARCHIVED (PASS / NO / expiry / operator) and FAILED are reachable from any non-terminal state.
INSERT INTO mbos.item_state_transitions (from_state, to_state)
SELECT s, t FROM unnest(ARRAY['DISCOVERED','NORMALIZED','RESEARCHING','SCORED','RECOMMENDED','AWAITING_APPROVAL',
                              'HELD','APPROVED','REJECTED','ACTING','ACTED','OUTCOME_RECORDED','LEARNED']) AS s,
              unnest(ARRAY['ARCHIVED','FAILED']) AS t
ON CONFLICT DO NOTHING;

CREATE OR REPLACE FUNCTION mbos.items_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.body->>'state' <> 'DISCOVERED' THEN
            RAISE EXCEPTION 'mbos: items must be created in DISCOVERED, got %', NEW.body->>'state';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'mbos: items are never deleted; transition to ARCHIVED' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NEW.body->>'item_id' <> OLD.body->>'item_id' THEN
        RAISE EXCEPTION 'mbos: item_id is immutable';
    END IF;
    IF (NEW.body->>'state') <> (OLD.body->>'state') AND NOT EXISTS (
        SELECT 1 FROM mbos.item_state_transitions
        WHERE from_state = OLD.body->>'state' AND to_state = NEW.body->>'state') THEN
        RAISE EXCEPTION 'mbos: illegal item transition % -> %', OLD.body->>'state', NEW.body->>'state';
    END IF;
    NEW.version := OLD.version + 1;
    RETURN NEW;
END $$;
CREATE TRIGGER items_guard BEFORE INSERT OR UPDATE OR DELETE ON mbos.items
    FOR EACH ROW EXECUTE FUNCTION mbos.items_guard();

-- ---------------------------------------------------------------- action_requests (current status; history = receipts)
CREATE TABLE mbos.action_requests (
    action_request_id text GENERATED ALWAYS AS (body->>'action_request_id') STORED PRIMARY KEY,
    item_id           text GENERATED ALWAYS AS (body->>'item_id') STORED NOT NULL REFERENCES mbos.items (item_id),
    status            text GENERATED ALWAYS AS (body->>'status') STORED NOT NULL,
    payload_hash      text GENERATED ALWAYS AS (body->>'payload_hash') STORED NOT NULL,
    idempotency_key   text GENERATED ALWAYS AS (body->>'idempotency_key') STORED NOT NULL UNIQUE,
    body              jsonb NOT NULL   -- payload_hash is re-derived from canonical JSON by the execution guard
);
CREATE INDEX action_requests_item_idx ON mbos.action_requests (item_id);

CREATE OR REPLACE FUNCTION mbos.action_requests_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'mbos: action requests are never deleted' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF (NEW.body - 'status') IS DISTINCT FROM (OLD.body - 'status') THEN
        RAISE EXCEPTION 'mbos: action request % is frozen; only status may change (MODIFY creates a new request)',
            OLD.body->>'action_request_id';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER action_requests_guard BEFORE UPDATE OR DELETE ON mbos.action_requests
    FOR EACH ROW EXECUTE FUNCTION mbos.action_requests_guard();

-- ---------------------------------------------------------------- approvals (append-only)
CREATE TABLE mbos.approvals (
    seq               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    approval_id       text GENERATED ALWAYS AS (body->>'approval_id') STORED UNIQUE NOT NULL,
    action_request_id text GENERATED ALWAYS AS (body->>'action_request_id') STORED NOT NULL
                      REFERENCES mbos.action_requests (action_request_id),
    decision          text GENERATED ALWAYS AS (body->>'decision') STORED NOT NULL,
    body              jsonb NOT NULL
);
CREATE INDEX approvals_areq_idx ON mbos.approvals (action_request_id, seq);

CREATE OR REPLACE FUNCTION mbos.approvals_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    want text;
BEGIN
    SELECT payload_hash INTO want FROM mbos.action_requests WHERE action_request_id = NEW.body->>'action_request_id';
    IF want IS NULL OR want <> NEW.body->>'payload_hash_seen' THEN
        RAISE EXCEPTION 'mbos: approval void — payload_hash_seen % does not match request payload_hash %',
            NEW.body->>'payload_hash_seen', want;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER approvals_guard BEFORE INSERT ON mbos.approvals FOR EACH ROW EXECUTE FUNCTION mbos.approvals_guard();
SELECT mbos.make_insert_only('mbos.approvals');

-- ---------------------------------------------------------------- receipts (insert-only, hash-chained)
CREATE SEQUENCE mbos.receipts_seq AS bigint MINVALUE 1;

CREATE TABLE mbos.receipts (
    seq               bigint PRIMARY KEY,
    receipt_id        text GENERATED ALWAYS AS (body->>'receipt_id') STORED UNIQUE NOT NULL,
    type              text GENERATED ALWAYS AS (body->>'type') STORED NOT NULL,
    item_id           text GENERATED ALWAYS AS (body->>'item_id') STORED,
    action_request_id text GENERATED ALWAYS AS (body->>'action_request_id') STORED,
    idempotency_key   text GENERATED ALWAYS AS (body->>'idempotency_key') STORED UNIQUE NOT NULL,
    body              jsonb NOT NULL,   -- the Receipt v1 document minus seq / prev_hash / row_hash
    prev_hash         text,
    row_hash          text NOT NULL,
    CHECK (NOT (body ? 'seq' OR body ? 'prev_hash' OR body ? 'row_hash')),
    CHECK (jsonb_typeof(body->'provenance_ids') = 'array' AND jsonb_array_length(body->'provenance_ids') >= 1),
    -- A7 / ADR-0005 guard check 8: MVP effector receipts are dry-run only. Lifting this needs a migration + ADR.
    CONSTRAINT mvp_dry_run_only CHECK (
        (body->>'type') NOT IN ('ACTION_EXECUTED', 'ACTION_FAILED')
        OR (body->'effector_response'->>'dry_run') = 'true')
);
CREATE INDEX receipts_item_idx ON mbos.receipts (item_id, seq);
CREATE INDEX receipts_areq_idx ON mbos.receipts (action_request_id, seq);

CREATE OR REPLACE FUNCTION mbos.receipt_row_hash(p_seq bigint, p_body jsonb, p_prev text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT 'sha256:' || encode(pg_catalog.sha256(convert_to(p_seq::text || '|' || p_body::text || '|' || coalesce(p_prev, ''), 'UTF8')), 'hex')
$$;

CREATE OR REPLACE FUNCTION mbos.receipts_chain() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    missing text;
BEGIN
    -- Under REPEATABLE READ / SERIALIZABLE the tail read below would use a stale snapshot and fork
    -- the chain, so receipts may only be written under READ COMMITTED.
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'mbos: receipts must be written under READ COMMITTED (got %)', current_setting('transaction_isolation');
    END IF;
    -- One chain writer at a time; held to commit, so seq order == chain order == commit order.
    PERFORM pg_advisory_xact_lock(hashtext('mbos.receipts.chain'));
    SELECT p INTO missing
      FROM jsonb_array_elements_text(NEW.body->'provenance_ids') AS p
     WHERE NOT EXISTS (SELECT 1 FROM mbos.provenance v WHERE v.provenance_id = p)
     LIMIT 1;
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'mbos: no receipt without provenance — % does not exist', missing;
    END IF;
    NEW.seq := nextval('mbos.receipts_seq');
    SELECT r.row_hash INTO NEW.prev_hash FROM mbos.receipts r ORDER BY r.seq DESC LIMIT 1;
    NEW.row_hash := mbos.receipt_row_hash(NEW.seq, NEW.body, NEW.prev_hash);
    RETURN NEW;
END $$;
CREATE TRIGGER receipts_chain BEFORE INSERT ON mbos.receipts FOR EACH ROW EXECUTE FUNCTION mbos.receipts_chain();
SELECT mbos.make_insert_only('mbos.receipts');

CREATE OR REPLACE FUNCTION mbos.verify_chain()
RETURNS TABLE (ok boolean, checked bigint, first_bad_seq bigint, reason text)
LANGUAGE plpgsql STABLE AS $$
DECLARE
    r record;
    expected_prev text := NULL;
    n bigint := 0;
BEGIN
    FOR r IN SELECT seq, body, prev_hash, row_hash FROM mbos.receipts ORDER BY seq LOOP
        n := n + 1;
        IF r.prev_hash IS DISTINCT FROM expected_prev THEN
            RETURN QUERY SELECT false, n, r.seq, 'prev_hash does not link to previous row_hash'; RETURN;
        END IF;
        IF r.row_hash <> mbos.receipt_row_hash(r.seq, r.body, r.prev_hash) THEN
            RETURN QUERY SELECT false, n, r.seq, 'row_hash does not match row content'; RETURN;
        END IF;
        expected_prev := r.row_hash;
    END LOOP;
    RETURN QUERY SELECT true, n, NULL::bigint, NULL::text;
END $$;

-- ---------------------------------------------------------------- outcomes (append-only)
CREATE TABLE mbos.outcomes (
    seq        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    outcome_id text GENERATED ALWAYS AS (body->>'outcome_id') STORED UNIQUE NOT NULL,
    item_id    text GENERATED ALWAYS AS (body->>'item_id') STORED NOT NULL REFERENCES mbos.items (item_id),
    body       jsonb NOT NULL
);
SELECT mbos.make_insert_only('mbos.outcomes');

-- ---------------------------------------------------------------- effector calls (dry-run log; idempotency anchor for A5)
CREATE TABLE mbos.effector_calls (
    seq               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    idempotency_key   text NOT NULL UNIQUE,
    action_request_id text NOT NULL REFERENCES mbos.action_requests (action_request_id),
    capability        text NOT NULL,
    provider          text NOT NULL,
    provider_msg_id   text NOT NULL,
    dry_run           boolean NOT NULL CONSTRAINT effector_mvp_dry_run_only CHECK (dry_run),
    request           jsonb NOT NULL,
    response          jsonb NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now()
);
SELECT mbos.make_insert_only('mbos.effector_calls');

-- ---------------------------------------------------------------- governance flags (kill switch; 05 owns semantics)
CREATE TABLE mbos.governance_flags (
    key        text PRIMARY KEY,   -- 'global_freeze' (L3) | 'capability_freeze:<capability>' (L2) | 'agent_freeze:<agent>' (L1)
    value      jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO mbos.governance_flags (key, value) VALUES ('global_freeze', '{"frozen": false}');

-- ---------------------------------------------------------------- LLM spend ledger (A8; LiteLLM virtual keys = lane 05)
CREATE TABLE mbos.llm_spend (
    seq        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agent_id   text NOT NULL,
    day        date NOT NULL,
    usd        numeric(12, 6) NOT NULL CHECK (usd >= 0),
    trace_id   text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX llm_spend_agent_day_idx ON mbos.llm_spend (agent_id, day);
SELECT mbos.make_insert_only('mbos.llm_spend');

-- ---------------------------------------------------------------- outbox (same txn as state change + receipt)
CREATE TABLE mbos.outbox (
    seq          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    topic        text NOT NULL,          -- 'operator.notify', 'item.state', projection topics …
    entity_id    text NOT NULL,
    payload      jsonb NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz
);
CREATE INDEX outbox_unpublished_idx ON mbos.outbox (seq) WHERE published_at IS NULL;

-- ---------------------------------------------------------------- grants
GRANT USAGE ON SCHEMA mbos TO agent_read, agent_write, gateway;
GRANT SELECT ON ALL TABLES IN SCHEMA mbos TO agent_read, agent_write, gateway;
-- agent_write deliberately gets UPDATE/DELETE on every table: A2 proves the TRIGGERS, not missing grants,
-- protect the ledgers.
GRANT INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA mbos TO agent_write;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA mbos TO agent_write;
GRANT INSERT ON mbos.effector_calls, mbos.receipts, mbos.provenance TO gateway;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA mbos TO gateway;
