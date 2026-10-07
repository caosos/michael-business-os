-- 0005_r1_integration.sql — Agent 01 integration rulings R1, R3, R5, R8 (ROUND_TWO_INTEGRATION.md).
--   R1: tables Agent 01's reference spine needs, on the canonical (04) schema:
--       effector_calls, panic_state (R5, replaces governance_flags), llm_spend, artifacts.
--       Agent 01's invariants are kept: insert-only, dry-run-only CHECKs.
--   R3 / ADR-0010: a proposed payload must carry its MBOS-CJSON-1 payload_hash.
--   R5: PANIC state (05 semantics) lives in Postgres: append-only revisions, sealed checksum, receipted,
--       fail-closed reader.
--   R8: dedup_key is a blocking key, not an identity.
-- Also aligns the item state machine with the edges Agent 01's acceptance suite uses.

-- ---------------------------------------------------------------------------
-- R3 / ADR-0010: payload hashes are MBOS-CJSON-1 (mbos.payload_hash = mbos.cjson_sha256, see 0000/0001).
-- ---------------------------------------------------------------------------
-- A proposed payload must hash (R3) to its declared payload_hash: a mismatch can never be approved
-- (guard check 3), so refuse it at the door.
CREATE FUNCTION mbos.areq_payload_hash_check() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.payload_hash <> mbos.payload_hash(NEW.payload) THEN
        RAISE EXCEPTION 'mbos: payload_hash % is not MBOS-CJSON-1 sha256 of the payload = % (ADR-0010)',
            NEW.payload_hash, mbos.payload_hash(NEW.payload) USING ERRCODE = 'MB007';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER ab_areq_payload_hash BEFORE INSERT ON mbos.action_requests
    FOR EACH ROW EXECUTE FUNCTION mbos.areq_payload_hash_check();

-- ---------------------------------------------------------------------------
-- R8: dedup_key is a blocking key. Identity = (source, source_listing_id) inside sources[].
-- ---------------------------------------------------------------------------
ALTER TABLE mbos.items DROP CONSTRAINT items_dedup_key_key;
CREATE INDEX items_dedup_key_idx ON mbos.items (dedup_key);
CREATE INDEX items_sources_gin ON mbos.items USING gin ((doc->'sources') jsonb_path_ops);

-- Item edges used by Agent 01's spine / acceptance suite.
UPDATE mbos.item_states SET terminal = false WHERE state = 'LEARNED';
INSERT INTO mbos.item_state_transitions VALUES
    ('NORMALIZED','SCORED','score directly when no research is needed (01 spine)'),
    ('HELD','APPROVED','YES on a held request (01 spine)'),
    ('LEARNED','ARCHIVED','any non-terminal state'),
    ('LEARNED','FAILED','any non-terminal state')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- R1: artifacts — content-addressed blobs (raw listing bytes, photos, documents). Insert-only.
-- Inline bytea for wave one; storage/location reserve the move to FS / Garage / SeaweedFS.
-- ---------------------------------------------------------------------------
CREATE TABLE mbos.artifacts (
    sha256     text PRIMARY KEY CHECK (sha256 ~ '^sha256:[0-9a-f]{64}$'),
    media_type text NOT NULL,
    byte_size  bigint NOT NULL CHECK (byte_size >= 0),
    storage    text NOT NULL DEFAULT 'inline' CHECK (storage IN ('inline','fs','s3')),
    location   text,
    content    bytea,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT artifacts_inline_content CHECK ((storage = 'inline') = (content IS NOT NULL)),
    CONSTRAINT artifacts_external_location CHECK (storage = 'inline' OR location IS NOT NULL),
    CONSTRAINT artifacts_content_addressed CHECK (
        content IS NULL OR (sha256 = 'sha256:' || encode(sha256(content), 'hex') AND byte_size = octet_length(content)))
);
SELECT mbos.make_append_only('mbos.artifacts');

-- Idempotent put: returns the address; existing content is never replaced.
CREATE FUNCTION mbos.put_artifact(p_content bytea, p_media_type text) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE h text := 'sha256:' || encode(sha256(p_content), 'hex');
BEGIN
    INSERT INTO mbos.artifacts (sha256, media_type, byte_size, content)
    VALUES (h, p_media_type, octet_length(p_content), p_content)
    ON CONFLICT (sha256) DO NOTHING;
    RETURN h;
END $$;

-- ---------------------------------------------------------------------------
-- R1: effector_calls — the record of each (dry-run) effector invocation and the A5 idempotency anchor.
-- Insert-only, dry_run forced. A call may only be recorded while its request is `executing`, which means
-- the gateway already wrote the ACTION_EXECUTING receipt: no action without a receipt.
-- ---------------------------------------------------------------------------
CREATE TABLE mbos.effector_calls (
    seq               bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    idempotency_key   text PRIMARY KEY,
    action_request_id text NOT NULL REFERENCES mbos.action_requests,
    capability        text NOT NULL,
    provider          text NOT NULL,
    provider_msg_id   text NOT NULL,
    dry_run           boolean NOT NULL CONSTRAINT effector_wave1_dry_run_only CHECK (dry_run),
    request           jsonb NOT NULL,
    response          jsonb NOT NULL CONSTRAINT effector_response_dry_run CHECK (response->'dry_run' = 'true'::jsonb),
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX effector_calls_areq_idx ON mbos.effector_calls (action_request_id);
SELECT mbos.make_append_only('mbos.effector_calls');

CREATE FUNCTION mbos.effector_calls_before_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE a mbos.action_requests;
BEGIN
    SELECT * INTO a FROM mbos.action_requests WHERE action_request_id = NEW.action_request_id;
    IF a.status IS DISTINCT FROM 'executing' THEN
        RAISE EXCEPTION 'mbos: effector call for % refused: request is %, not executing (receipt ACTION_EXECUTING first)',
            NEW.action_request_id, a.status USING ERRCODE = 'MB004';
    END IF;
    IF NEW.idempotency_key <> a.idempotency_key OR NEW.capability <> a.capability THEN
        RAISE EXCEPTION 'mbos: effector call must use the request''s idempotency_key and capability'
            USING ERRCODE = 'MB409';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER aa_effector_calls_before_insert BEFORE INSERT ON mbos.effector_calls
    FOR EACH ROW EXECUTE FUNCTION mbos.effector_calls_before_insert();

-- Exactly-once (A5): the first call wins; a replay returns the original response and does not act.
CREATE FUNCTION mbos.record_effector_call(p_action_request_id text, p_provider text, p_provider_msg_id text,
                                          p_request jsonb, p_response jsonb)
RETURNS TABLE (response jsonb, replayed boolean) LANGUAGE plpgsql AS $$
DECLARE a mbos.action_requests; prior jsonb;
BEGIN
    SELECT * INTO a FROM mbos.action_requests WHERE action_request_id = p_action_request_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'mbos: action request % not found', p_action_request_id USING ERRCODE = 'MB404'; END IF;
    SELECT c.response INTO prior FROM mbos.effector_calls c WHERE c.idempotency_key = a.idempotency_key;
    IF FOUND THEN RETURN QUERY SELECT prior, true; RETURN; END IF;
    INSERT INTO mbos.effector_calls (idempotency_key, action_request_id, capability, provider, provider_msg_id,
                                     dry_run, request, response)
    VALUES (a.idempotency_key, a.action_request_id, a.capability, p_provider, p_provider_msg_id,
            coalesce((p_response->>'dry_run')::boolean, false), p_request, p_response);
    RETURN QUERY SELECT p_response, false;
END $$;

-- ---------------------------------------------------------------------------
-- R1: llm_spend — LLM metering ledger behind LiteLLM caps (A8). Insert-only. (Real-world money is
-- budget_ledger; C10: two ledgers.)
-- ---------------------------------------------------------------------------
CREATE TABLE mbos.llm_spend (
    seq        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agent_id   text NOT NULL,
    day        date NOT NULL DEFAULT (now() AT TIME ZONE 'UTC')::date,
    usd        numeric(12,6) NOT NULL CHECK (usd >= 0),
    model_id   text,
    prompt_tokens     int CHECK (prompt_tokens >= 0),
    completion_tokens int CHECK (completion_tokens >= 0),
    trace_id   text,
    receipt_id text REFERENCES mbos.receipts,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX llm_spend_agent_day_idx ON mbos.llm_spend (agent_id, day);
SELECT mbos.make_append_only('mbos.llm_spend');

-- Authorize-then-record under a per-agent lock so concurrent calls cannot overrun the cap.
-- NULL cap = deny (fail closed).
CREATE FUNCTION mbos.llm_spend_authorize(p_agent_id text, p_est_usd numeric, p_cap_usd numeric,
                                         p_day date DEFAULT (now() AT TIME ZONE 'UTC')::date)
RETURNS numeric LANGUAGE plpgsql AS $$
DECLARE spent numeric;
BEGIN
    IF p_cap_usd IS NULL THEN
        RAISE EXCEPTION 'mbos: no LLM cap for % — denied (fail-closed)', p_agent_id USING ERRCODE = 'MB006';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('mbos.llm:' || p_agent_id, 0));
    SELECT coalesce(sum(usd), 0) INTO spent FROM mbos.llm_spend WHERE agent_id = p_agent_id AND day = p_day;
    IF spent + p_est_usd > p_cap_usd THEN
        RAISE EXCEPTION 'mbos: % LLM spend % + % exceeds daily cap %', p_agent_id, spent, p_est_usd, p_cap_usd
            USING ERRCODE = 'MB006';
    END IF;
    RETURN p_cap_usd - spent - p_est_usd;   -- headroom after this call
END $$;

-- ---------------------------------------------------------------------------
-- R5: PANIC state (Agent 05 semantics, mbos.governance.panic/1), in Postgres.
-- Each change is a new revision row holding the full sealed body; current = highest revision.
-- FAIL CLOSED: no row, a bad checksum, a wrong schema or a malformed body all read as FROZEN.
-- Engaging a freeze is open to gateway / agent_write / policy_admin (freezing is always safe);
-- releasing anything requires policy_admin (a human governance act).
-- ---------------------------------------------------------------------------
CREATE TABLE mbos.panic_state (
    revision     int PRIMARY KEY CHECK (revision >= 1),
    global_state text NOT NULL CHECK (global_state IN ('RUNNING','FROZEN')),
    body         jsonb NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);
SELECT mbos.make_append_only('mbos.panic_state');

CREATE FUNCTION mbos.panic_seal(body jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE STRICT AS $$
    SELECT (body - 'checksum') || jsonb_build_object('checksum', mbos.cjson_sha256(body - 'checksum'))
$$;

CREATE FUNCTION mbos.panic_read()
RETURNS TABLE (global_state text, agents jsonb, capabilities jsonb, revision int, readable boolean, error text)
LANGUAGE plpgsql STABLE AS $$
DECLARE b jsonb; r int;
BEGIN
    BEGIN
        SELECT p.body, p.revision INTO b, r FROM mbos.panic_state p ORDER BY p.revision DESC LIMIT 1;
        IF b IS NULL THEN
            RETURN QUERY SELECT 'FROZEN', '{}'::jsonb, '{}'::jsonb, 0, false, 'no panic state (run mbos.panic_init)'; RETURN;
        END IF;
        IF b->>'schema' IS DISTINCT FROM 'mbos.governance.panic/1' THEN
            RETURN QUERY SELECT 'FROZEN', '{}'::jsonb, '{}'::jsonb, r, false, 'wrong schema'; RETURN;
        END IF;
        IF b->>'checksum' IS DISTINCT FROM mbos.panic_seal(b)->>'checksum' THEN
            RETURN QUERY SELECT 'FROZEN', '{}'::jsonb, '{}'::jsonb, r, false, 'checksum mismatch'; RETURN;
        END IF;
        IF (b->>'revision')::int IS DISTINCT FROM r
           OR b->'global'->>'state' NOT IN ('RUNNING','FROZEN')
           OR jsonb_typeof(b->'agents') IS DISTINCT FROM 'object'
           OR jsonb_typeof(b->'capabilities') IS DISTINCT FROM 'object' THEN
            RETURN QUERY SELECT 'FROZEN', '{}'::jsonb, '{}'::jsonb, r, false, 'malformed body'; RETURN;
        END IF;
        RETURN QUERY SELECT b->'global'->>'state', b->'agents', b->'capabilities', r, true, NULL::text;
    EXCEPTION WHEN OTHERS THEN
        RETURN QUERY SELECT 'FROZEN', '{}'::jsonb, '{}'::jsonb, 0, false, 'unreadable: ' || SQLERRM;
    END;
END $$;

-- Reasons (agent, capability, category) is blocked; empty array = clear. Mirrors 05 PanicState.blocks().
CREATE FUNCTION mbos.panic_blocks(p_agent_id text, p_capability text, p_category text) RETURNS text[]
LANGUAGE plpgsql STABLE AS $$
DECLARE s record; k text; reasons text[] := '{}';
BEGIN
    SELECT * INTO s FROM mbos.panic_read();
    IF NOT s.readable THEN RETURN ARRAY['PANIC_STATE_UNREADABLE:' || s.error]; END IF;
    IF s.global_state <> 'RUNNING' THEN reasons := array_append(reasons, 'PANIC_L3_FROZEN'); END IF;
    IF p_agent_id IS NOT NULL AND s.agents ? p_agent_id THEN reasons := array_append(reasons, ('PANIC_L1_AGENT:' || p_agent_id)); END IF;
    FOR k IN SELECT jsonb_object_keys(s.capabilities) LOOP
        IF p_category IS NOT NULL AND k = 'category:' || p_category THEN
            reasons := array_append(reasons, ('PANIC_L2_CATEGORY:' || p_category));
        ELSIF p_capability IS NOT NULL AND (k = p_capability
              OR (right(k, 2) = '.*' AND left(p_capability, length(k) - 1) = left(k, length(k) - 1))) THEN
            reasons := array_append(reasons, ('PANIC_L2_CAPABILITY:' || k));
        END IF;
    END LOOP;
    RETURN reasons;
END $$;

CREATE FUNCTION mbos.panic_require_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM mbos.require_receipt(ARRAY['KILL_SWITCH_CHANGED'], 'entity_id', 'panic:' || NEW.revision);
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER zz_panic_receipt AFTER INSERT ON mbos.panic_state
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION mbos.panic_require_receipt();

CREATE FUNCTION mbos._panic_write(p_after jsonb, p_before jsonb, p_actor jsonb, p_intent text,
                                  p_provenance_ids text[], p_idempotency_key text) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE sealed jsonb := mbos.panic_seal(p_after); rc mbos.receipts;
BEGIN
    INSERT INTO mbos.panic_state (revision, global_state, body)
    VALUES ((sealed->>'revision')::int, sealed->'global'->>'state', sealed);
    rc := mbos.append_receipt(jsonb_build_object(
        'type', 'KILL_SWITCH_CHANGED', 'actor', p_actor, 'intent', p_intent, 'entity_type', 'panic_state',
        'entity_id', 'panic:' || (sealed->>'revision'), 'effect', 'update', 'idempotency_key', p_idempotency_key,
        'provenance_ids', to_jsonb(p_provenance_ids), 'before_state', p_before, 'after_state', sealed));
    RETURN rc.receipt_id;
END $$;

-- Create the first revision. Defaults to FROZEN (05: releasing is a separate, receipted act).
CREATE FUNCTION mbos.panic_init(p_actor jsonb, p_reason text, p_provenance_ids text[], p_idempotency_key text,
                                p_state text DEFAULT 'FROZEN') RETURNS text
LANGUAGE plpgsql AS $$
DECLARE prev mbos.receipts;
BEGIN
    prev := mbos.idempotent_receipt(p_idempotency_key, 'KILL_SWITCH_CHANGED');
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.receipt_id; END IF;
    PERFORM pg_advisory_xact_lock(7340004005);
    IF EXISTS (SELECT 1 FROM mbos.panic_state) THEN
        RAISE EXCEPTION 'mbos: panic state already initialised' USING ERRCODE = 'MB409';
    END IF;
    IF p_state = 'RUNNING' AND NOT (pg_has_role(current_user, 'policy_admin', 'MEMBER')
                                    OR pg_has_role(current_user, 'mbos_owner', 'MEMBER')) THEN
        RAISE EXCEPTION 'mbos: only policy_admin may initialise PANIC as RUNNING' USING ERRCODE = '42501';
    END IF;
    RETURN mbos._panic_write(jsonb_build_object(
        'schema', 'mbos.governance.panic/1', 'revision', 1, 'agents', '{}'::jsonb, 'capabilities', '{}'::jsonb,
        'global', jsonb_build_object('state', p_state, 'changed_at', mbos.utc_iso(now()),
                                     'changed_by', p_actor->>'id', 'reason', p_reason)),
        NULL, p_actor, 'PANIC init: ' || p_state || ' — ' || p_reason, p_provenance_ids, p_idempotency_key);
END $$;

-- One change, atomically: L3 global, L2 capability/prefix/'category:x', L1 agent. Mirrors 05 _mutate():
-- an unreadable state is rebuilt as FROZEN, never repaired into RUNNING.
CREATE FUNCTION mbos.panic_mutate(p_level text, p_target text, p_engage boolean, p_actor jsonb, p_reason text,
                                  p_provenance_ids text[], p_idempotency_key text) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE prev mbos.receipts; s record; before jsonb; after jsonb; stamp jsonb; key text; next_rev int;
BEGIN
    prev := mbos.idempotent_receipt(p_idempotency_key, 'KILL_SWITCH_CHANGED');
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.receipt_id; END IF;
    IF NOT p_engage AND NOT (pg_has_role(current_user, 'policy_admin', 'MEMBER')
                             OR pg_has_role(current_user, 'mbos_owner', 'MEMBER')) THEN
        RAISE EXCEPTION 'mbos: releasing a freeze requires policy_admin' USING ERRCODE = '42501';
    END IF;
    PERFORM pg_advisory_xact_lock(7340004005);
    SELECT coalesce(max(revision), 0) + 1 INTO next_rev FROM mbos.panic_state;
    SELECT * INTO s FROM mbos.panic_read();
    stamp := jsonb_build_object('changed_at', mbos.utc_iso(now()), 'changed_by', p_actor->>'id', 'reason', p_reason);
    IF s.readable THEN
        SELECT p.body INTO before FROM mbos.panic_state p ORDER BY p.revision DESC LIMIT 1;
        after := before - 'checksum';
    ELSE
        before := NULL;
        after := jsonb_build_object('schema', 'mbos.governance.panic/1', 'agents', '{}'::jsonb,
                     'capabilities', '{}'::jsonb,
                     'global', jsonb_build_object('state', 'FROZEN', 'changed_at', mbos.utc_iso(now()),
                                                  'changed_by', 'system', 'reason', 'rebuilt from unreadable state: ' || s.error));
    END IF;
    IF p_level = 'L3' THEN
        after := jsonb_set(after, '{global}', jsonb_build_object('state', CASE WHEN p_engage THEN 'FROZEN' ELSE 'RUNNING' END) || stamp);
    ELSIF p_level IN ('L1','L2') THEN
        IF coalesce(p_target, '') = '' THEN
            RAISE EXCEPTION 'mbos: % needs a target', p_level USING ERRCODE = 'MB004';
        END IF;
        key := CASE p_level WHEN 'L1' THEN 'agents' ELSE 'capabilities' END;
        after := jsonb_set(after, ARRAY[key],
                           CASE WHEN p_engage THEN (after->key) || jsonb_build_object(p_target, stamp)
                                ELSE (after->key) - p_target END);
    ELSE
        RAISE EXCEPTION 'mbos: unknown PANIC level %', p_level USING ERRCODE = 'MB004';
    END IF;
    after := after || jsonb_build_object('revision', next_rev);
    RETURN mbos._panic_write(after, before, p_actor,
        format('PANIC %s %s%s: %s', p_level, CASE WHEN p_engage THEN 'engage' ELSE 'release' END,
               coalesce(' ' || p_target, ''), p_reason),
        p_provenance_ids, p_idempotency_key);
END $$;

-- ---------------------------------------------------------------------------
-- Grants for the new objects
-- ---------------------------------------------------------------------------
REVOKE ALL ON mbos.artifacts, mbos.effector_calls, mbos.llm_spend, mbos.panic_state FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION mbos.put_artifact(bytea, text),
    mbos.record_effector_call(text, text, text, jsonb, jsonb), mbos.llm_spend_authorize(text, numeric, numeric, date),
    mbos.panic_seal(jsonb), mbos.panic_read(), mbos.panic_blocks(text, text, text),
    mbos._panic_write(jsonb, jsonb, jsonb, text, text[], text), mbos.panic_init(jsonb, text, text[], text, text),
    mbos.panic_mutate(text, text, boolean, jsonb, text, text[], text) FROM PUBLIC;

GRANT SELECT ON mbos.artifacts, mbos.effector_calls, mbos.llm_spend, mbos.panic_state
    TO agent_read, agent_write, gateway, approver, policy_admin;
GRANT EXECUTE ON FUNCTION mbos.panic_seal(jsonb),
    mbos.panic_read(), mbos.panic_blocks(text, text, text)
    TO agent_read, agent_write, gateway, approver, policy_admin;

GRANT INSERT ON mbos.artifacts, mbos.llm_spend TO agent_write, gateway;
GRANT EXECUTE ON FUNCTION mbos.put_artifact(bytea, text), mbos.llm_spend_authorize(text, numeric, numeric, date)
    TO agent_write, gateway;

GRANT INSERT ON mbos.effector_calls TO gateway;   -- R4: the gateway owns execution
GRANT EXECUTE ON FUNCTION mbos.record_effector_call(text, text, text, jsonb, jsonb) TO gateway;

GRANT INSERT ON mbos.panic_state TO agent_write, gateway, policy_admin;
GRANT EXECUTE ON FUNCTION mbos._panic_write(jsonb, jsonb, jsonb, text, text[], text),
    mbos.panic_init(jsonb, text, text[], text, text),
    mbos.panic_mutate(text, text, boolean, jsonb, text, text[], text)
    TO agent_write, gateway, policy_admin;
GRANT EXECUTE ON FUNCTION mbos.record_provenance(jsonb), mbos.append_receipt(jsonb) TO agent_write, gateway, policy_admin;
