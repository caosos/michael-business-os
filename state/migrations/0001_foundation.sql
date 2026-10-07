-- 0001_foundation.sql — MBOS state spine: IDs, provenance, hash-chained receipts, outbox, verify_chain.
-- Owner: Agent 04 (lane D). Contracts: docs/research/contracts v1.0.0 (ADR-0004), frozen by Agent 01.
-- Runs inside one transaction as role mbos_owner (see mbos_state/migrate.py).
--
-- Core law, enforced mechanically here and in 0002:
--   No action without a receipt.   (deferred constraint triggers: state rows need a same-tx receipt)
--   No receipt without provenance. (receipt trigger: >=1 provenance_id, every id must resolve)

CREATE SCHEMA IF NOT EXISTS mbos;
COMMENT ON SCHEMA mbos IS 'Michael Business OS authoritative state spine (Postgres is the source of truth; ADR-0001).';

-- ---------------------------------------------------------------------------
-- Helpers
-- ---------------------------------------------------------------------------

-- Crockford-base32 ULID: 48-bit ms timestamp + 80 random bits (26 chars).
-- Randomness from gen_random_uuid() (core since PG13); bytes chosen to avoid the v4 version/variant nibbles.
CREATE FUNCTION mbos.ulid() RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL SAFE AS $$
DECLARE
    alphabet CONSTANT text := '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
    ms   bigint := floor(extract(epoch FROM clock_timestamp()) * 1000)::bigint;
    u1   bytea  := uuid_send(gen_random_uuid());
    u2   bytea  := uuid_send(gen_random_uuid());
    bits text;
    res  text := '';
    i    int;
BEGIN
    bits := '00' || substring(ms::bit(64)::text FROM 17);           -- 2 pad + 48 time bits
    FOR i IN 0..5 LOOP bits := bits || get_byte(u1, i)::bit(8)::text; END LOOP;  -- 48 random
    FOR i IN 0..3 LOOP bits := bits || get_byte(u2, i)::bit(8)::text; END LOOP;  -- 32 random
    FOR i IN 0..25 LOOP
        res := res || substr(alphabet, substring(bits FROM i * 5 + 1 FOR 5)::bit(5)::int + 1, 1);
    END LOOP;
    RETURN res;
END $$;

CREATE FUNCTION mbos.new_id(prefix text) RETURNS text
LANGUAGE sql VOLATILE PARALLEL SAFE AS $$ SELECT prefix || '_' || mbos.ulid() $$;

CREATE FUNCTION mbos.sha256_text(t text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT 'sha256:' || encode(sha256(convert_to(t, 'UTF8')), 'hex')
$$;

-- Reference hash for a JSON payload (ActionRequest.payload_hash). RECOMMENDATION to 01/05: use this one
-- function (or an RFC 8785 equivalent) everywhere so the execution guard re-check cannot drift.
CREATE FUNCTION mbos.payload_hash(p jsonb) RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$ SELECT mbos.sha256_text(p::text) $$;

CREATE FUNCTION mbos.utc_iso(t timestamptz) RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT to_char(t AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
$$;

-- Drop top-level keys whose value is JSON null (nested nulls are preserved, unlike jsonb_strip_nulls).
CREATE FUNCTION mbos.jsonb_strip_top_nulls(j jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT coalesce(jsonb_object_agg(key, value), '{}'::jsonb)
    FROM jsonb_each(j) WHERE value <> 'null'::jsonb
$$;

-- Generic guard for insert-only ledgers. Fires for EVERY role, including the table owner.
-- (A superuser can still ALTER TABLE ... DISABLE TRIGGER; that is what verify_chain + anchoring detect.)
CREATE FUNCTION mbos.reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'mbos: % on %.% is forbidden (append-only ledger)', TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME
        USING ERRCODE = 'MB001', HINT = 'Record a new row (and receipt) instead of changing history.';
END $$;

-- Attach UPDATE/DELETE/TRUNCATE guards to a table.
CREATE FUNCTION mbos.make_append_only(tbl regclass) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    EXECUTE format('CREATE TRIGGER zz_append_only_row BEFORE UPDATE OR DELETE ON %s
                    FOR EACH ROW EXECUTE FUNCTION mbos.reject_mutation()', tbl);
    EXECUTE format('CREATE TRIGGER zz_append_only_truncate BEFORE TRUNCATE ON %s
                    FOR EACH STATEMENT EXECUTE FUNCTION mbos.reject_mutation()', tbl);
END $$;

-- ---------------------------------------------------------------------------
-- Provenance (contract: provenance.schema.json) — append-only
-- ---------------------------------------------------------------------------
CREATE TABLE mbos.provenance (
    provenance_id  text PRIMARY KEY CHECK (provenance_id ~ '^prov_[0-9A-HJKMNP-TV-Z]{26}$'),
    seq            bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    created_at     timestamptz NOT NULL DEFAULT now(),
    actor_type     text NOT NULL CHECK (actor_type IN ('agent','human','system','external')),
    agent_name     text,
    human_actor    text,
    basis          text NOT NULL CHECK (basis IN ('FACT','INFERENCE','RECOMMENDATION','UNKNOWN')),
    source_uri     text,
    fetched_at     timestamptz,
    model_id       text,
    model_version  text,
    prompt_hash    text CHECK (prompt_hash ~ '^sha256:[0-9a-f]{64}$'),
    tool_name      text,
    tool_version   text,
    config_version text,
    approval_id    text CHECK (approval_id ~ '^appr_[0-9A-HJKMNP-TV-Z]{26}$'),  -- FK added in 0002
    trace_id       text,
    inputs_used    jsonb CHECK (inputs_used IS NULL OR jsonb_typeof(inputs_used) = 'array'),
    derived_from   text[],
    confidence     numeric CHECK (confidence BETWEEN 0 AND 1),
    -- Agent 01 resolution rule (contract anyOf): source, model, human decision, or deterministic tool.
    CONSTRAINT provenance_resolves CHECK (
           (source_uri IS NOT NULL AND fetched_at IS NOT NULL)
        OR (model_id IS NOT NULL AND model_version IS NOT NULL AND prompt_hash IS NOT NULL)
        OR (approval_id IS NOT NULL)
        OR (tool_name IS NOT NULL AND tool_version IS NOT NULL)
    )
);
ALTER TABLE mbos.provenance ALTER COLUMN provenance_id SET DEFAULT mbos.new_id('prov');
SELECT mbos.make_append_only('mbos.provenance');

-- ---------------------------------------------------------------------------
-- Receipts (contract: receipt.schema.json) — insert-only, hash-chained, gapless seq
-- ---------------------------------------------------------------------------
CREATE TABLE mbos.receipts (
    receipt_id          text PRIMARY KEY CHECK (receipt_id ~ '^rcpt_[0-9A-HJKMNP-TV-Z]{26}$'),
    seq                 bigint NOT NULL UNIQUE CHECK (seq >= 1),
    ts                  timestamptz NOT NULL DEFAULT now(),
    schema_version      text NOT NULL DEFAULT '1.0.0' CHECK (schema_version = '1.0.0'),
    type                text NOT NULL CHECK (type IN (
                            'ITEM_STATE_CHANGED','SCORE_RECORDED','RECOMMENDATION_RECORDED',
                            'ACTION_PROPOSED','POLICY_DECIDED','APPROVAL_REQUESTED','APPROVAL_DECIDED',
                            'BUDGET_RESERVED','BUDGET_COMMITTED','BUDGET_RELEASED',
                            'ACTION_EXECUTING','ACTION_EXECUTED','ACTION_FAILED',
                            'OUTCOME_RECORDED','LESSON_RECORDED','CONFIG_VERSION_BUMPED',
                            'KILL_SWITCH_CHANGED','GRANT_CREATED','GRANT_REVOKED','INJECTION_SUSPECTED')),
    actor               jsonb NOT NULL CHECK (
                            jsonb_typeof(actor) = 'object'
                            AND actor->>'type' IN ('agent','human','system','external')
                            AND coalesce(actor->>'id','') <> ''),
    intent              text NOT NULL CHECK (length(intent) > 0),
    item_id             text CHECK (item_id ~ '^itm_[0-9A-HJKMNP-TV-Z]{26}$'),
    action_request_id   text CHECK (action_request_id ~ '^areq_[0-9A-HJKMNP-TV-Z]{26}$'),
    approval_id         text CHECK (approval_id ~ '^appr_[0-9A-HJKMNP-TV-Z]{26}$'),
    capability          text,
    entity_type         text,
    entity_id           text,
    effect              text CHECK (effect IN ('none','create','update','logical_delete','send','pay','publish','schedule','commit')),
    tool_name           text,
    payload_hash        text CHECK (payload_hash ~ '^sha256:[0-9a-f]{64}$'),
    inputs_hash         text CHECK (inputs_hash ~ '^sha256:[0-9a-f]{64}$'),
    idempotency_key     text NOT NULL UNIQUE CHECK (length(idempotency_key) > 0),
    before_state        jsonb CHECK (before_state IS NULL OR jsonb_typeof(before_state) IN ('object','null')),
    after_state         jsonb CHECK (after_state IS NULL OR jsonb_typeof(after_state) IN ('object','null')),
    policy_decision_ref text,
    budget_effect       jsonb CHECK (budget_effect IS NULL OR (budget_effect ? 'category' AND budget_effect ? 'amount' AND budget_effect ? 'currency')),
    llm_cost            jsonb CHECK (llm_cost IS NULL OR jsonb_typeof(llm_cost) = 'object'),
    effector_response   jsonb CHECK (effector_response IS NULL OR jsonb_typeof(effector_response) = 'object'),
    provenance_ids      text[] NOT NULL CHECK (cardinality(provenance_ids) >= 1),
    artifact_hashes     text[],
    outcome_id          text CHECK (outcome_id ~ '^outc_[0-9A-HJKMNP-TV-Z]{26}$'),
    details             jsonb CHECK (details IS NULL OR details->>'kind' IN ('comms','marketing','money','generic')),
    prev_hash           text CHECK (prev_hash ~ '^sha256:[0-9a-f]{64}$'),
    row_hash            text NOT NULL UNIQUE CHECK (row_hash ~ '^sha256:[0-9a-f]{64}$'),
    -- Internal (not part of Receipt v1, not hashed):
    canonical           text NOT NULL,          -- exact bytes that row_hash covers
    tx_id               xid8 NOT NULL,          -- writing transaction; used by same-tx invariant checks

    CONSTRAINT receipts_genesis_only_once CHECK ((seq = 1) = (prev_hash IS NULL)),
    CONSTRAINT receipts_prev_hash_unique UNIQUE (prev_hash),   -- no forks
    -- Contract allOf conditionals:
    CONSTRAINT receipts_action_fields CHECK (
        type NOT IN ('ACTION_PROPOSED','POLICY_DECIDED','APPROVAL_REQUESTED','APPROVAL_DECIDED',
                     'BUDGET_RESERVED','BUDGET_COMMITTED','BUDGET_RELEASED',
                     'ACTION_EXECUTING','ACTION_EXECUTED','ACTION_FAILED')
        OR (action_request_id IS NOT NULL AND capability IS NOT NULL AND payload_hash IS NOT NULL)),
    CONSTRAINT receipts_approval_decided_fields CHECK (type <> 'APPROVAL_DECIDED' OR approval_id IS NOT NULL),
    CONSTRAINT receipts_executed_fields CHECK (
        type NOT IN ('ACTION_EXECUTED','ACTION_FAILED')
        OR (approval_id IS NOT NULL AND effector_response IS NOT NULL AND effect IS NOT NULL)),
    -- Wave one / MVP (A7, MICHAEL_DECISIONS #4): every effector receipt is a dry run. Going live means a
    -- reviewed migration that drops this constraint — deliberately not a runtime toggle.
    CONSTRAINT receipts_wave1_dry_run_only CHECK (
        effector_response IS NULL OR effector_response->'dry_run' = 'true'::jsonb)
);
COMMENT ON COLUMN mbos.receipts.canonical IS 'Canonical JSON text of the Receipt v1 document without row_hash (includes prev_hash). row_hash = sha256(canonical).';
CREATE INDEX receipts_item_idx ON mbos.receipts (item_id) WHERE item_id IS NOT NULL;
CREATE INDEX receipts_areq_idx ON mbos.receipts (action_request_id) WHERE action_request_id IS NOT NULL;
CREATE INDEX receipts_tx_idx   ON mbos.receipts (tx_id);
CREATE INDEX receipts_type_ts_idx ON mbos.receipts (type, ts);

-- Receipt v1 document (without row_hash) as the canonical jsonb that is hashed.
CREATE FUNCTION mbos.receipt_canonical(r mbos.receipts) RETURNS jsonb
LANGUAGE sql STABLE PARALLEL SAFE AS $$
    SELECT mbos.jsonb_strip_top_nulls(jsonb_build_object(
        'receipt_id', r.receipt_id, 'seq', r.seq, 'ts', mbos.utc_iso(r.ts),
        'schema_version', r.schema_version, 'type', r.type, 'actor', r.actor, 'intent', r.intent,
        'item_id', r.item_id, 'action_request_id', r.action_request_id, 'approval_id', r.approval_id,
        'capability', r.capability, 'entity_type', r.entity_type, 'entity_id', r.entity_id,
        'effect', r.effect, 'tool_name', r.tool_name, 'payload_hash', r.payload_hash,
        'inputs_hash', r.inputs_hash, 'idempotency_key', r.idempotency_key,
        'before_state', r.before_state, 'after_state', r.after_state,
        'policy_decision_ref', r.policy_decision_ref, 'budget_effect', r.budget_effect,
        'llm_cost', r.llm_cost, 'effector_response', r.effector_response,
        'provenance_ids', to_jsonb(r.provenance_ids), 'artifact_hashes', to_jsonb(r.artifact_hashes),
        'outcome_id', r.outcome_id, 'details', r.details))
        -- prev_hash is required by the contract even when null (genesis), so it is never stripped
        || jsonb_build_object('prev_hash', r.prev_hash)
$$;

-- Full contract document (what consumers and the A10 conformance test see).
CREATE FUNCTION mbos.receipt_document(r mbos.receipts) RETURNS jsonb
LANGUAGE sql STABLE PARALLEL SAFE AS $$
    SELECT mbos.receipt_canonical(r) || jsonb_build_object('row_hash', r.row_hash)
$$;

CREATE FUNCTION mbos.receipts_before_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    missing text[];
    last_seq bigint;
    last_hash text;
BEGIN
    -- No receipt without provenance: every id must resolve to a stored provenance row.
    SELECT array_agg(p) INTO missing
    FROM unnest(NEW.provenance_ids) AS p
    WHERE NOT EXISTS (SELECT 1 FROM mbos.provenance v WHERE v.provenance_id = p);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'mbos: receipt references unknown provenance ids %', missing USING ERRCODE = 'MB002';
    END IF;

    -- Serialize chain appends. Held to commit, so the next writer sees this row (READ COMMITTED takes a
    -- fresh snapshot per statement inside a volatile function). Under REPEATABLE READ a stale head yields a
    -- UNIQUE(seq)/UNIQUE(prev_hash) violation: fail closed, never a fork.
    PERFORM pg_advisory_xact_lock(7340004001);
    SELECT r.seq, r.row_hash INTO last_seq, last_hash FROM mbos.receipts r ORDER BY r.seq DESC LIMIT 1;

    -- The writer never chooses chain fields.
    NEW.receipt_id     := coalesce(NEW.receipt_id, mbos.new_id('rcpt'));
    NEW.ts             := coalesce(NEW.ts, now());
    NEW.schema_version := coalesce(NEW.schema_version, '1.0.0');
    NEW.seq            := coalesce(last_seq, 0) + 1;
    NEW.prev_hash      := last_hash;
    NEW.tx_id          := pg_current_xact_id();
    NEW.canonical      := mbos.receipt_canonical(NEW)::text;
    NEW.row_hash       := mbos.sha256_text(NEW.canonical);
    RETURN NEW;
END $$;

CREATE TRIGGER aa_receipts_chain BEFORE INSERT ON mbos.receipts
    FOR EACH ROW EXECUTE FUNCTION mbos.receipts_before_insert();
SELECT mbos.make_append_only('mbos.receipts');

-- ---------------------------------------------------------------------------
-- Outbox — one row per receipt, written by trigger in the receipt's transaction (state + receipt + outbox
-- commit together by construction). Consumers: Twenty projection, ntfy alerts, DBOS wake hints.
-- ---------------------------------------------------------------------------
CREATE TABLE mbos.outbox (
    outbox_id      text PRIMARY KEY DEFAULT mbos.new_id('obx') CHECK (outbox_id ~ '^obx_[0-9A-HJKMNP-TV-Z]{26}$'),
    seq            bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    created_at     timestamptz NOT NULL DEFAULT now(),
    topic          text NOT NULL,
    receipt_id     text NOT NULL UNIQUE REFERENCES mbos.receipts (receipt_id),
    aggregate_type text,
    aggregate_id   text,
    payload        jsonb NOT NULL,
    available_at   timestamptz NOT NULL DEFAULT now(),
    dispatched_at  timestamptz,
    attempts       int NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error     text,
    tx_id          xid8 NOT NULL DEFAULT pg_current_xact_id()
);
CREATE INDEX outbox_pending_idx ON mbos.outbox (available_at, seq) WHERE dispatched_at IS NULL;

CREATE FUNCTION mbos.receipts_to_outbox() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, mbos AS $$
BEGIN
    INSERT INTO mbos.outbox (topic, receipt_id, aggregate_type, aggregate_id, payload)
    VALUES ('receipt.' || lower(NEW.type), NEW.receipt_id,
            CASE WHEN NEW.item_id IS NOT NULL THEN 'item' ELSE NEW.entity_type END,
            coalesce(NEW.item_id, NEW.entity_id),
            mbos.receipt_document(NEW));
    RETURN NULL;
END $$;
CREATE TRIGGER zz_receipts_outbox AFTER INSERT ON mbos.receipts
    FOR EACH ROW EXECUTE FUNCTION mbos.receipts_to_outbox();

-- Only delivery bookkeeping may change; the message itself is immutable. Deletes only via outbox_prune().
CREATE FUNCTION mbos.outbox_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF current_setting('mbos.outbox_prune', true) = 'on' AND OLD.dispatched_at IS NOT NULL THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'mbos: outbox rows are deleted only by mbos.outbox_prune() after dispatch' USING ERRCODE = 'MB001';
    END IF;
    IF (NEW.outbox_id, NEW.seq, NEW.created_at, NEW.topic, NEW.receipt_id, NEW.aggregate_type,
        NEW.aggregate_id, NEW.payload, NEW.tx_id)
       IS DISTINCT FROM
       (OLD.outbox_id, OLD.seq, OLD.created_at, OLD.topic, OLD.receipt_id, OLD.aggregate_type,
        OLD.aggregate_id, OLD.payload, OLD.tx_id) THEN
        RAISE EXCEPTION 'mbos: outbox message content is immutable' USING ERRCODE = 'MB001';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER aa_outbox_guard BEFORE UPDATE OR DELETE ON mbos.outbox
    FOR EACH ROW EXECUTE FUNCTION mbos.outbox_guard();
CREATE TRIGGER zz_outbox_no_truncate BEFORE TRUNCATE ON mbos.outbox
    FOR EACH STATEMENT EXECUTE FUNCTION mbos.reject_mutation();

-- Relay API (role outbox_relay). Idempotent consumers key on receipt_id.
CREATE FUNCTION mbos.outbox_claim(p_limit int DEFAULT 100)
RETURNS SETOF mbos.outbox LANGUAGE sql AS $$
    SELECT * FROM mbos.outbox
    WHERE dispatched_at IS NULL AND available_at <= now()
    ORDER BY seq LIMIT p_limit
    FOR UPDATE SKIP LOCKED
$$;

CREATE FUNCTION mbos.outbox_mark(p_outbox_id text, p_ok boolean, p_error text DEFAULT NULL,
                                 p_retry_after interval DEFAULT interval '1 minute')
RETURNS void LANGUAGE sql AS $$
    UPDATE mbos.outbox SET
        attempts      = attempts + 1,
        dispatched_at = CASE WHEN p_ok THEN now() END,
        last_error    = CASE WHEN p_ok THEN NULL ELSE p_error END,
        available_at  = CASE WHEN p_ok THEN available_at ELSE now() + p_retry_after END
    WHERE outbox_id = p_outbox_id AND dispatched_at IS NULL
$$;

CREATE FUNCTION mbos.outbox_prune(p_older_than interval DEFAULT interval '30 days')
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, mbos AS $$
DECLARE n bigint;
BEGIN
    PERFORM set_config('mbos.outbox_prune', 'on', true);
    DELETE FROM mbos.outbox WHERE dispatched_at IS NOT NULL AND dispatched_at < now() - p_older_than;
    GET DIAGNOSTICS n = ROW_COUNT;
    PERFORM set_config('mbos.outbox_prune', 'off', true);
    RETURN n;   -- the receipts ledger keeps the full history; the outbox is only a delivery queue
END $$;

-- ---------------------------------------------------------------------------
-- Chain verification
-- ---------------------------------------------------------------------------
CREATE FUNCTION mbos.chain_head()
RETURNS TABLE (seq bigint, receipt_id text, row_hash text, ts timestamptz)
LANGUAGE sql STABLE AS $$
    SELECT r.seq, r.receipt_id, r.row_hash, r.ts FROM mbos.receipts r ORDER BY r.seq DESC LIMIT 1
$$;

-- Checks, in seq order from p_from_seq:
--   1. seq is gapless and starts where expected (detects deleted rows)
--   2. prev_hash equals the previous row's row_hash (detects re-ordering, insertion, rewrites)
--   3. row_hash = sha256(canonical)                     (detects edits to the hashed bytes)
--   4. canonical::jsonb = receipt_canonical(row)        (detects edits to any column)
--   5. optional anchor: the head must equal or extend a previously exported (seq, row_hash)
--      (detects tail truncation / whole-tail rewrites, which a self-contained chain cannot)
CREATE FUNCTION mbos.verify_chain(p_from_seq bigint DEFAULT 1,
                                  p_anchor_seq bigint DEFAULT NULL, p_anchor_hash text DEFAULT NULL)
RETURNS TABLE (ok boolean, receipts_checked bigint, first_bad_seq bigint, reason text)
LANGUAGE plpgsql STABLE AS $$
DECLARE
    r mbos.receipts;
    expected_seq bigint := p_from_seq;
    prev text;
    n bigint := 0;
    anchor_seen boolean := false;
BEGIN
    IF p_from_seq > 1 THEN
        SELECT x.row_hash INTO prev FROM mbos.receipts x WHERE x.seq = p_from_seq - 1;
        IF prev IS NULL THEN
            RETURN QUERY SELECT false, 0::bigint, p_from_seq - 1, 'missing receipt before start seq'; RETURN;
        END IF;
    END IF;
    FOR r IN SELECT * FROM mbos.receipts x WHERE x.seq >= p_from_seq ORDER BY x.seq LOOP
        IF r.seq <> expected_seq THEN
            RETURN QUERY SELECT false, n, expected_seq, format('seq gap: expected %s, found %s', expected_seq, r.seq); RETURN;
        END IF;
        IF r.prev_hash IS DISTINCT FROM prev THEN
            RETURN QUERY SELECT false, n, r.seq, 'prev_hash does not match previous row_hash'; RETURN;
        END IF;
        IF mbos.sha256_text(r.canonical) IS DISTINCT FROM r.row_hash THEN
            RETURN QUERY SELECT false, n, r.seq, 'row_hash does not match canonical bytes'; RETURN;
        END IF;
        IF r.canonical::jsonb IS DISTINCT FROM mbos.receipt_canonical(r) THEN
            RETURN QUERY SELECT false, n, r.seq, 'stored columns differ from hashed canonical document'; RETURN;
        END IF;
        IF p_anchor_seq IS NOT NULL AND r.seq = p_anchor_seq THEN
            IF r.row_hash IS DISTINCT FROM p_anchor_hash THEN
                RETURN QUERY SELECT false, n, r.seq, 'row_hash differs from external anchor'; RETURN;
            END IF;
            anchor_seen := true;
        END IF;
        prev := r.row_hash;
        expected_seq := expected_seq + 1;
        n := n + 1;
    END LOOP;
    IF p_anchor_seq IS NOT NULL AND NOT anchor_seen THEN
        RETURN QUERY SELECT false, n, p_anchor_seq, 'anchored receipt is missing (tail truncated?)'; RETURN;
    END IF;
    RETURN QUERY SELECT true, n, NULL::bigint, NULL::text;
END $$;
