-- 0026_record_acquisition.sql — READY_QUEUE D-31 (F-114 ruling, F-115).
--   * The system never buys anything: Michael buys off-system, and capital deploys when HE records it.
--     mbos.record_acquisition(item_id, amount_usd, note, actor, provenance_ids, idempotency_key): SECURITY DEFINER, owner_channel
--     session AND a human actor with an id AND provenance_ids[1] a human provenance naming that human. It writes, atomically:
--       1. a drafted purchase action request (capability money.purchase, payload kind owner_acquisition) + ACTION_PROPOSED (human),
--       2. the request moved to 'executed' (new owner-only transition drafted->executed, empty role list: only mbos_owner/definer),
--       3. a dry-run BUDGET_COMMITTED receipt (category purchase, USD, human actor). The 0017 trigger turns it into a capital
--          'deploy' entry and REFUSES it above available_to_deploy (MB006, everything rolls back). An unfunded ledger is refused too.
--     Amount 0.01..10,000,000 with at most 2 decimals. Idempotent on the key (returns the BUDGET_COMMITTED receipt id).
--   * areq_require_receipt also accepts BUDGET_COMMITTED (after_state.status executed) as the receipt for that move.
--   * F-115: record_outcome refuses a closing outcome for an item whose capital was already closed (MB006). The ledger already
--     ignored it silently (capital_one_close_per_item); now the caller is told. Idempotent replays still return the first result.

INSERT INTO mbos.action_request_transitions VALUES ('drafted', 'executed', '{}');

CREATE OR REPLACE FUNCTION mbos.areq_require_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM mbos.require_receipt(ARRAY['ACTION_PROPOSED'], 'action_request_id', NEW.action_request_id);
    ELSIF NEW.status IS DISTINCT FROM OLD.status OR NEW.policy_decision_ref IS DISTINCT FROM OLD.policy_decision_ref THEN
        PERFORM mbos.require_receipt(
            ARRAY['POLICY_DECIDED','APPROVAL_REQUESTED','APPROVAL_DECIDED','ACTION_EXECUTING','ACTION_EXECUTED',
                  'ACTION_FAILED','OUTCOME_RECORDED','KILL_SWITCH_CHANGED','BUDGET_COMMITTED'],
            'action_request_id', NEW.action_request_id, jsonb_build_object('status', NEW.status));
    END IF;
    RETURN NULL;
END $$;

CREATE FUNCTION mbos._capital_item_closed(p_item_id text, p_kind text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, mbos AS $$
    SELECT EXISTS (SELECT 1 FROM mbos.capital_closing_kinds k WHERE k.kind = p_kind)
       AND EXISTS (SELECT 1 FROM mbos.capital_ledger l WHERE l.kind = 'close' AND l.item_id = p_item_id)
$$;
REVOKE EXECUTE ON FUNCTION mbos._capital_item_closed(text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION mbos._capital_item_closed(text, text) TO agent_write, approver, owner_channel, mbos_owner;

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
    IF mbos._capital_item_closed(p_outcome->>'item_id', p_outcome->>'kind') THEN      -- F-115
        RAISE EXCEPTION 'mbos: item % is already closed (a closing outcome already returned its capital); a second % is refused',
            p_outcome->>'item_id', p_outcome->>'kind' USING ERRCODE = 'MB006';
    END IF;
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

CREATE FUNCTION mbos.record_acquisition(p_item_id text, p_amount_usd numeric, p_note text, p_actor jsonb,
                                        p_provenance_ids text[], p_idempotency_key text) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, mbos AS $$
DECLARE prev mbos.receipts; note text := btrim(coalesce(p_note, '')); who text; pid text; areq text := mbos.new_id('areq');
        payload jsonb; st record; rc mbos.receipts;
BEGIN
    IF NOT pg_has_role(session_user, 'owner_channel', 'MEMBER') THEN
        RAISE EXCEPTION 'mbos: role % may not record an acquisition (owner_channel only)', session_user USING ERRCODE = '42501';
    END IF;
    IF p_actor->>'type' IS DISTINCT FROM 'human' OR coalesce(btrim(p_actor->>'id'), '') = '' THEN
        RAISE EXCEPTION 'mbos: an acquisition is recorded only by a human (actor.type human with an id), got actor %', p_actor
            USING ERRCODE = '42501';
    END IF;
    who := btrim(p_actor->>'id');
    IF p_amount_usd IS NULL OR p_amount_usd < 0.01 OR p_amount_usd > 10000000 OR p_amount_usd <> round(p_amount_usd, 2) THEN
        RAISE EXCEPTION 'mbos: acquisition amount must be 0.01..10,000,000 USD with at most 2 decimals, got %', p_amount_usd
            USING ERRCODE = 'MB004';
    END IF;
    IF note = '' OR length(note) > 2000 THEN
        RAISE EXCEPTION 'mbos: an acquisition needs a note (up to 2000 characters)' USING ERRCODE = 'MB004';
    END IF;
    pid := p_provenance_ids[1];
    IF pid IS NULL OR NOT EXISTS (SELECT 1 FROM mbos.provenance WHERE provenance_id = pid AND actor_type = 'human' AND human_actor = who) THEN
        RAISE EXCEPTION 'mbos: provenance_ids[1] must be a human provenance record naming %', who USING ERRCODE = 'MB004';
    END IF;
    prev := mbos.idempotent_receipt(p_idempotency_key, 'BUDGET_COMMITTED');
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.receipt_id; END IF;
    IF NOT EXISTS (SELECT 1 FROM mbos.items WHERE item_id = p_item_id) THEN
        RAISE EXCEPTION 'mbos: item % not found', p_item_id USING ERRCODE = 'MB404';
    END IF;
    SELECT * INTO st FROM mbos.capital_state(p_item_id);
    IF NOT st.active THEN
        RAISE EXCEPTION 'mbos: the capital ledger is not funded; fund it before recording an acquisition' USING ERRCODE = 'MB006';
    END IF;
    payload := jsonb_build_object('kind', 'owner_acquisition', 'amount_usd', p_amount_usd, 'note', note, 'recorded_by', who);
    INSERT INTO mbos.action_requests (action_request_id, item_id, proposed_by, capability, category, payload, payload_hash,
                                      idempotency_key, estimated_cost, max_cost, reversibility, tier, expires_at, provenance_ids)
    VALUES (areq, p_item_id, who, 'money.purchase', 'purchase', payload, mbos.payload_hash(payload), 'acq:' || p_idempotency_key,
            jsonb_build_object('amount', p_amount_usd, 'currency', 'USD'), jsonb_build_object('amount', p_amount_usd, 'currency', 'USD'),
            'irreversible', 0, now(), p_provenance_ids);
    PERFORM mbos.append_receipt(jsonb_build_object(
        'type', 'ACTION_PROPOSED', 'actor', p_actor, 'intent', who || ' recorded an off-system purchase: ' || note,
        'item_id', p_item_id, 'action_request_id', areq, 'capability', 'money.purchase', 'payload_hash', mbos.payload_hash(payload),
        'entity_type', 'action_request', 'entity_id', areq, 'effect', 'none', 'idempotency_key', p_idempotency_key || ':proposed',
        'provenance_ids', to_jsonb(p_provenance_ids),
        'after_state', jsonb_build_object('status', 'drafted', 'tier', 0, 'category', 'purchase', 'reversibility', 'irreversible')));
    UPDATE mbos.action_requests SET status = 'executed' WHERE action_request_id = areq;
    rc := mbos.append_receipt(jsonb_build_object(
        'type', 'BUDGET_COMMITTED', 'actor', p_actor, 'intent', who || ' bought it off-system: ' || note, 'item_id', p_item_id,
        'action_request_id', areq, 'capability', 'money.purchase', 'payload_hash', mbos.payload_hash(payload),
        'entity_type', 'action_request', 'entity_id', areq, 'effect', 'none', 'idempotency_key', p_idempotency_key,
        'provenance_ids', to_jsonb(p_provenance_ids),
        'budget_effect', jsonb_build_object('category', 'purchase', 'amount', p_amount_usd, 'currency', 'USD'),
        'after_state', jsonb_build_object('status', 'executed', 'kind', 'owner_acquisition', 'mode', 'dry_run'),
        'details', jsonb_build_object('kind', 'money', 'dry_run', true)));
    RETURN rc.receipt_id;
END $$;

REVOKE EXECUTE ON FUNCTION mbos.record_acquisition(text, numeric, text, jsonb, text[], text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION mbos.record_acquisition(text, numeric, text, jsonb, text[], text) TO owner_channel;
