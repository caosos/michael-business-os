-- 0018_human_outcome_ui.sql — READY_QUEUE P-06-19 (found by 06 in P-06-18; ruling by Agent 01).
--
-- D-18 closes an item's capital only on a HUMAN-recorded closing outcome, and that outcome is entered by Michael
-- through the Operator UI (login mbos_operator_ui = role approver). Until now only agent_write could call
-- mbos.record_outcome, so the owner channel could not record the very outcome capital close needs.
--
--   * approver gets EXECUTE on mbos.record_outcome, INSERT on mbos.outcomes, and the executed -> outcome_recorded
--     edge in mbos.action_request_transitions (it already has UPDATE (status) on action_requests).
--   * Inside the function: a session that is NOT an agent_write member (i.e. the Operator UI) must pass
--     actor {type: human, id: <non-empty>}; any other actor is refused (42501). agent_write sessions (State MCP,
--     mbos_dbos) are unchanged: they may still record agent/system outcomes, and those never move capital.
--   * Capital movement stays approver-only: the 0017 derivation trigger is untouched.
-- The body below is 0003's record_outcome with only the actor guard added.

CREATE OR REPLACE FUNCTION mbos.record_outcome(p_outcome jsonb, p_actor jsonb, p_intent text, p_idempotency_key text)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE o mbos.outcomes; prev mbos.receipts; a mbos.action_requests; after jsonb;
BEGIN
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

GRANT INSERT ON mbos.outcomes TO approver;
GRANT EXECUTE ON FUNCTION mbos.record_outcome(jsonb, jsonb, text, text) TO approver;
UPDATE mbos.action_request_transitions SET allowed_roles = '{agent_write,gateway,approver}'
WHERE from_status = 'executed' AND to_status = 'outcome_recorded';
