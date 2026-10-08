-- 0023_panic_owner_only_release.sql — READY_QUEUE D-28 (G-18 F-85 + F-86).
--   F-85: the workflow login (mbos_dbos = agent_write + gateway) released PANIC by appending a human-claimed KILL_SWITCH_CHANGED
--   receipt and INSERTing a sealed RUNNING panic_state row itself (the constraint trigger only checked that *a* receipt existed).
--     * panic_state loses every direct INSERT grant; panic_set / panic_init / _panic_write become SECURITY DEFINER (owner writes the row).
--       Their role checks now use session_user, because current_user is the definer inside them.
--     * append_receipt refuses any receipt with entity_type panic_state or entity_id 'panic:%' unless it runs as the table owner, i.e. inside those
--       definer functions. (Other receipt types are unchanged.)
--     * panic_require_receipt now reads the receipt: a release (engage false, or a RUNNING global) needs a human actor claim AND an
--       approver / mbos_owner session. ENGAGE stays open to gateway through panic_set. panic_seal is a pure function and stays granted.
--   F-86: record_outcome with a human actor claim now needs approver / mbos_owner for ANY session (0018 exempted agent_write members).
--     agent_write may still record agent/system outcomes.
--   Refusals are 42501.

CREATE OR REPLACE FUNCTION mbos.panic_set(p_level text, p_target text, p_engage boolean, p_actor jsonb, p_reason text,
                               p_provenance_ids text[], p_idempotency_key text) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, mbos AS $$
DECLARE
    prev mbos.receipts; s record; before jsonb; after jsonb; stamp jsonb; key text; next_rev int;
    sealed jsonb; rc mbos.receipts; a mbos.action_requests; owner boolean;
BEGIN
    prev := mbos.idempotent_receipt(p_idempotency_key, 'KILL_SWITCH_CHANGED');
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.receipt_id; END IF;
    owner := pg_has_role(session_user, 'mbos_owner', 'MEMBER');
    IF p_engage AND NOT (owner OR pg_has_role(session_user, 'gateway', 'MEMBER')
                         OR pg_has_role(session_user, 'approver', 'MEMBER')
                         OR pg_has_role(session_user, 'policy_admin', 'MEMBER')) THEN
        RAISE EXCEPTION 'mbos: role % may not engage PANIC', session_user USING ERRCODE = '42501';
    END IF;
    IF NOT p_engage AND NOT (owner OR pg_has_role(session_user, 'approver', 'MEMBER')) THEN
        RAISE EXCEPTION 'mbos: releasing PANIC requires approver (Michael)' USING ERRCODE = '42501';
    END IF;
    IF p_level NOT IN ('L1','L2','L3') THEN
        RAISE EXCEPTION 'mbos: unknown PANIC level %', p_level USING ERRCODE = 'MB004';
    END IF;
    IF (p_level = 'L3') <> (p_target IS NULL) OR (p_target IS NOT NULL AND btrim(p_target) = '') THEN
        RAISE EXCEPTION 'mbos: PANIC target must be NULL for L3 and set for L1/L2' USING ERRCODE = 'MB004';
    END IF;
    IF coalesce(btrim(p_reason), '') = '' THEN
        RAISE EXCEPTION 'mbos: PANIC change needs a reason' USING ERRCODE = 'MB004';
    END IF;

    PERFORM pg_advisory_xact_lock(7340004005);
    SELECT coalesce(max(revision), 0) + 1 INTO next_rev FROM mbos.panic_state;
    SELECT * INTO s FROM mbos.panic_read();
    stamp := jsonb_build_object('changed_at', mbos.utc_iso(now()), 'changed_by', p_actor->>'id', 'reason', p_reason);
    IF s.readable THEN
        SELECT p.body INTO before FROM mbos.panic_state p ORDER BY p.revision DESC LIMIT 1;
        after := before - 'checksum';
    ELSE   -- an unreadable or empty state is rebuilt FROZEN, never repaired into RUNNING
        before := NULL;
        after := jsonb_build_object('schema', 'mbos.governance.panic/1', 'agents', '{}'::jsonb,
                     'capabilities', '{}'::jsonb,
                     'global', jsonb_build_object('state', 'FROZEN', 'changed_at', mbos.utc_iso(now()),
                                                  'changed_by', 'system', 'reason', 'rebuilt from: ' || s.error));
    END IF;
    IF p_level = 'L3' THEN
        after := jsonb_set(after, '{global}',
                           jsonb_build_object('state', CASE WHEN p_engage THEN 'FROZEN' ELSE 'RUNNING' END) || stamp);
    ELSE
        key := CASE p_level WHEN 'L1' THEN 'agents' ELSE 'capabilities' END;
        after := jsonb_set(after, ARRAY[key], CASE WHEN p_engage THEN (after->key) || jsonb_build_object(p_target, stamp)
                                                   ELSE (after->key) - p_target END);
    END IF;
    sealed := mbos.panic_seal(after || jsonb_build_object('revision', next_rev));

    INSERT INTO mbos.panic_state (revision, global_state, body, level, target, engage, actor, reason)
    VALUES (next_rev, sealed->'global'->>'state', sealed, p_level, p_target, p_engage, p_actor, p_reason);
    rc := mbos.append_receipt(jsonb_build_object(
        'type', 'KILL_SWITCH_CHANGED', 'actor', p_actor, 'entity_type', 'panic_state', 'entity_id', 'panic:' || next_rev,
        'intent', format('PANIC %s %s%s: %s', p_level, CASE WHEN p_engage THEN 'engage' ELSE 'release' END,
                         coalesce(' ' || p_target, ''), p_reason),
        'effect', 'update', 'idempotency_key', p_idempotency_key, 'provenance_ids', to_jsonb(p_provenance_ids),
        'before_state', before, 'after_state', sealed));

    -- L3 engage: requests approved but not started are cancelled now, each with its own receipt.
    IF p_level = 'L3' AND p_engage THEN
        FOR a IN SELECT * FROM mbos.action_requests WHERE status IN ('approved','auto_approved')
                 ORDER BY created_at FOR UPDATE LOOP
            UPDATE mbos.action_requests SET status = 'cancelled_by_freeze' WHERE action_request_id = a.action_request_id;
            PERFORM mbos.append_receipt(jsonb_build_object(
                'type', 'KILL_SWITCH_CHANGED', 'actor', p_actor, 'item_id', a.item_id,
                'action_request_id', a.action_request_id, 'capability', a.capability, 'payload_hash', a.payload_hash,
                'entity_type', 'action_request', 'entity_id', a.action_request_id, 'effect', 'none',
                'intent', 'L3 PANIC: cancel unstarted approved request (' || p_reason || ')',
                'idempotency_key', p_idempotency_key || ':cancel:' || a.action_request_id,
                'provenance_ids', to_jsonb(p_provenance_ids),
                'before_state', jsonb_build_object('status', a.status),
                'after_state', jsonb_build_object('status', 'cancelled_by_freeze', 'panic_revision', next_rev)));
        END LOOP;
    END IF;
    RETURN rc.receipt_id;
END $$;


CREATE OR REPLACE FUNCTION mbos._panic_write(p_after jsonb, p_before jsonb, p_actor jsonb, p_intent text,
                                             p_provenance_ids text[], p_idempotency_key text) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, mbos AS $$
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

CREATE OR REPLACE FUNCTION mbos.panic_init(p_actor jsonb, p_reason text, p_provenance_ids text[], p_idempotency_key text,
                                           p_state text DEFAULT 'FROZEN') RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, mbos AS $$
DECLARE prev mbos.receipts;
BEGIN
    prev := mbos.idempotent_receipt(p_idempotency_key, 'KILL_SWITCH_CHANGED');
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.receipt_id; END IF;
    PERFORM pg_advisory_xact_lock(7340004005);
    IF EXISTS (SELECT 1 FROM mbos.panic_state) THEN
        RAISE EXCEPTION 'mbos: panic state already initialised' USING ERRCODE = 'MB409';
    END IF;
    IF p_state = 'RUNNING' AND NOT (pg_has_role(session_user, 'policy_admin', 'MEMBER')
                                    OR pg_has_role(session_user, 'mbos_owner', 'MEMBER')) THEN
        RAISE EXCEPTION 'mbos: only policy_admin may initialise PANIC as RUNNING' USING ERRCODE = '42501';
    END IF;
    RETURN mbos._panic_write(jsonb_build_object(
        'schema', 'mbos.governance.panic/1', 'revision', 1, 'agents', '{}'::jsonb, 'capabilities', '{}'::jsonb,
        'global', jsonb_build_object('state', p_state, 'changed_at', mbos.utc_iso(now()),
                                     'changed_by', p_actor->>'id', 'reason', p_reason)),
        NULL, p_actor, 'PANIC init: ' || p_state || ' — ' || p_reason, p_provenance_ids, p_idempotency_key);
END $$;

-- The constraint trigger reads the receipt. Release = engage false, or (no engage flag, i.e. init/_panic_write) a RUNNING global.
CREATE OR REPLACE FUNCTION mbos.panic_require_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE rc mbos.receipts; release boolean := coalesce(NOT NEW.engage, NEW.global_state = 'RUNNING');
BEGIN
    PERFORM mbos.require_receipt(ARRAY['KILL_SWITCH_CHANGED'], 'entity_id', 'panic:' || NEW.revision);
    IF release THEN
        SELECT * INTO rc FROM mbos.receipts WHERE tx_id = pg_current_xact_id() AND type = 'KILL_SWITCH_CHANGED'
           AND entity_id = 'panic:' || NEW.revision ORDER BY seq DESC LIMIT 1;
        IF rc.actor->>'type' IS DISTINCT FROM 'human' OR coalesce(btrim(rc.actor->>'id'), '') = ''
           OR NOT (pg_has_role(session_user, 'approver', 'MEMBER') OR pg_has_role(session_user, 'mbos_owner', 'MEMBER')
                   OR (NEW.engage IS NULL AND pg_has_role(session_user, 'policy_admin', 'MEMBER'))) THEN
            RAISE EXCEPTION 'mbos: releasing PANIC (revision %) needs a human receipt actor and an approver session, got actor % as %',
                NEW.revision, rc.actor, session_user USING ERRCODE = '42501';
        END IF;
    END IF;
    RETURN NULL;
END $$;

-- Only the definer functions above (running as the table owner) may write a panic_state receipt (set_action_status's freeze cancels use another entity).
CREATE OR REPLACE FUNCTION mbos.append_receipt(r jsonb) RETURNS mbos.receipts
LANGUAGE plpgsql AS $$
DECLARE rec mbos.receipts;
BEGIN
    IF (r->>'entity_type' = 'panic_state' OR r->>'entity_id' LIKE 'panic:%')
       AND current_user::text IS DISTINCT FROM (SELECT relowner::regrole::text FROM pg_class WHERE oid = 'mbos.panic_state'::regclass) THEN
        RAISE EXCEPTION 'mbos: role % may not append a PANIC receipt directly (use mbos.panic_set)', current_user USING ERRCODE = '42501';
    END IF;
    rec := mbos.idempotent_receipt(r->>'idempotency_key', r->>'type');
    IF rec.receipt_id IS NOT NULL THEN RETURN rec; END IF;
    rec := jsonb_populate_record(NULL::mbos.receipts,
                                 r - ARRAY['seq','prev_hash','row_hash','canonical','tx_id','schema_version']);
    INSERT INTO mbos.receipts SELECT rec.* RETURNING * INTO rec;
    RETURN rec;
END $$;

REVOKE INSERT ON mbos.panic_state FROM agent_write, gateway, policy_admin, approver;
REVOKE EXECUTE ON FUNCTION mbos._panic_write(jsonb, jsonb, jsonb, text, text[], text) FROM gateway, policy_admin, approver, agent_write;

-- F-86: a human outcome claim needs an approver / owner session, whoever else the login is.
CREATE OR REPLACE FUNCTION mbos.record_outcome(p_outcome jsonb, p_actor jsonb, p_intent text, p_idempotency_key text)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE o mbos.outcomes; prev mbos.receipts; a mbos.action_requests; after jsonb;
BEGIN
    IF p_actor->>'type' = 'human' AND NOT (pg_has_role(session_user, 'owner_channel', 'MEMBER')
                                           OR pg_has_role(session_user, 'approver', 'MEMBER')
                                           OR pg_has_role(session_user, 'mbos_owner', 'MEMBER')) THEN
        RAISE EXCEPTION 'mbos: role % may not record a human-claimed outcome (owner channel only)', session_user USING ERRCODE = '42501';
    END IF;
    IF NOT pg_has_role(session_user, 'agent_write', 'MEMBER')
       AND (p_actor->>'type' IS DISTINCT FROM 'human' OR coalesce(btrim(p_actor->>'id'), '') = '') THEN
        RAISE EXCEPTION 'mbos: role % may record only a human outcome (actor.type human with an id), got actor %',
            session_user, p_actor USING ERRCODE = '42501';
    END IF;
    prev := mbos.idempotent_receipt(p_idempotency_key, 'OUTCOME_RECORDED');
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.outcome_id; END IF;
    o := jsonb_populate_record(NULL::mbos.outcomes, p_outcome);
    INSERT INTO mbos.outcomes (outcome_id, item_id, action_request_id, scorecard_id, observed_at, kind,
                               predicted_vs_actual, realized, attribution, notes, provenance_ids)
    VALUES (coalesce(o.outcome_id, mbos.new_id('outc')), o.item_id, o.action_request_id, o.scorecard_id,
            coalesce(o.observed_at, now()), o.kind, o.predicted_vs_actual, o.realized, o.attribution, o.notes,
            o.provenance_ids)
    RETURNING * INTO o;
    after := jsonb_build_object('kind', o.kind, 'realized', o.realized);
    IF o.action_request_id IS NOT NULL THEN
        SELECT * INTO a FROM mbos.action_requests WHERE action_request_id = o.action_request_id FOR UPDATE;
        IF a.status = 'executed' THEN
            UPDATE mbos.action_requests SET status = 'outcome_recorded' WHERE action_request_id = a.action_request_id;
            after := after || jsonb_build_object('status', 'outcome_recorded');
        END IF;
    END IF;
    PERFORM mbos.append_receipt(jsonb_build_object(
        'type', 'OUTCOME_RECORDED', 'actor', p_actor, 'intent', p_intent, 'item_id', o.item_id,
        'action_request_id', o.action_request_id, 'outcome_id', o.outcome_id, 'entity_type', 'outcome',
        'entity_id', o.outcome_id, 'effect', 'create', 'idempotency_key', p_idempotency_key,
        'provenance_ids', to_jsonb(o.provenance_ids), 'after_state', after));
    RETURN o.outcome_id;
END $$;

