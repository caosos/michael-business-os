-- 0003_api.sql — the write API. Each function performs state change + receipt (+ outbox, via trigger) in
-- the caller's single transaction, so it composes with a DBOS @transaction or any psycopg/SQLAlchemy txn.
-- All functions are SECURITY INVOKER: table privileges of the calling role still apply (0004).
-- Every function takes an idempotency_key; replaying the same key returns the original result (no-op).
--
-- SQLSTATEs: MB001 immutable, MB002 provenance, MB003 missing receipt, MB004 illegal transition,
--            MB005 approval invalid, MB006 budget, MB404 not found, MB409 conflict.

CREATE FUNCTION mbos.idempotent_receipt(p_key text, p_type text) RETURNS mbos.receipts
LANGUAGE plpgsql STABLE AS $$
DECLARE r mbos.receipts;
BEGIN
    SELECT * INTO r FROM mbos.receipts WHERE idempotency_key = p_key;
    IF FOUND AND r.type <> p_type THEN
        RAISE EXCEPTION 'mbos: idempotency key % already used for a % receipt', p_key, r.type USING ERRCODE = 'MB409';
    END IF;
    RETURN r;
END $$;

-- Insert a Receipt v1 document. seq / prev_hash / row_hash are always computed by the chain trigger.
CREATE FUNCTION mbos.append_receipt(r jsonb) RETURNS mbos.receipts
LANGUAGE plpgsql AS $$
DECLARE rec mbos.receipts;
BEGIN
    rec := mbos.idempotent_receipt(r->>'idempotency_key', r->>'type');
    IF rec.receipt_id IS NOT NULL THEN RETURN rec; END IF;
    rec := jsonb_populate_record(NULL::mbos.receipts,
                                 r - ARRAY['seq','prev_hash','row_hash','canonical','tx_id','schema_version']);
    INSERT INTO mbos.receipts SELECT rec.* RETURNING * INTO rec;
    RETURN rec;
END $$;

CREATE FUNCTION mbos.record_provenance(p jsonb) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE v mbos.provenance; id text;
BEGIN
    v := jsonb_populate_record(NULL::mbos.provenance, p);
    INSERT INTO mbos.provenance (provenance_id, created_at, actor_type, agent_name, human_actor, basis, source_uri,
        fetched_at, model_id, model_version, prompt_hash, tool_name, tool_version, config_version, approval_id,
        trace_id, inputs_used, derived_from, confidence)
    VALUES (coalesce(v.provenance_id, mbos.new_id('prov')), coalesce(v.created_at, now()), v.actor_type, v.agent_name,
        v.human_actor, v.basis, v.source_uri, v.fetched_at, v.model_id, v.model_version, v.prompt_hash, v.tool_name,
        v.tool_version, v.config_version, v.approval_id, v.trace_id, v.inputs_used, v.derived_from, v.confidence)
    RETURNING provenance_id INTO id;
    RETURN id;
END $$;

-- ---------------------------------------------------------------------------
-- Items
-- ---------------------------------------------------------------------------
CREATE FUNCTION mbos.create_item(p_doc jsonb, p_actor jsonb, p_intent text, p_provenance_ids text[],
                                 p_idempotency_key text) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE it mbos.items; prev mbos.receipts;
BEGIN
    prev := mbos.idempotent_receipt(p_idempotency_key, 'ITEM_STATE_CHANGED');
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.item_id; END IF;
    IF coalesce(p_doc->>'state', 'DISCOVERED') NOT IN ('DISCOVERED','NORMALIZED') THEN
        RAISE EXCEPTION 'mbos: items enter the flow as DISCOVERED or NORMALIZED' USING ERRCODE = 'MB004';
    END IF;
    INSERT INTO mbos.items (item_id, type, category, state, dedup_key, doc)
    VALUES (coalesce(p_doc->>'item_id', mbos.new_id('itm')), p_doc->>'type', p_doc->>'category',
            coalesce(p_doc->>'state', 'DISCOVERED'), p_doc->>'dedup_key', p_doc)
    RETURNING * INTO it;
    PERFORM mbos.append_receipt(jsonb_build_object(
        'type', 'ITEM_STATE_CHANGED', 'actor', p_actor, 'intent', p_intent, 'item_id', it.item_id,
        'entity_type', 'item', 'entity_id', it.item_id, 'effect', 'create', 'idempotency_key', p_idempotency_key,
        'provenance_ids', to_jsonb(p_provenance_ids), 'before_state', NULL,
        'after_state', jsonb_build_object('state', it.state, 'version', it.version, 'type', it.type,
                                          'category', it.category, 'dedup_key', it.dedup_key)));
    RETURN it.item_id;
END $$;

CREATE FUNCTION mbos.transition_item(p_item_id text, p_to_state text, p_actor jsonb, p_intent text,
                                     p_provenance_ids text[], p_idempotency_key text,
                                     p_expected_version int DEFAULT NULL, p_extra jsonb DEFAULT '{}')
RETURNS text LANGUAGE plpgsql AS $$
DECLARE it mbos.items; prev mbos.receipts; old_state text; old_version int; rc mbos.receipts;
BEGIN
    prev := mbos.idempotent_receipt(p_idempotency_key, 'ITEM_STATE_CHANGED');
    IF prev.receipt_id IS NOT NULL THEN
        IF prev.item_id IS DISTINCT FROM p_item_id OR prev.after_state->>'state' IS DISTINCT FROM p_to_state THEN
            RAISE EXCEPTION 'mbos: idempotency key % was used for a different transition', p_idempotency_key USING ERRCODE = 'MB409';
        END IF;
        RETURN prev.receipt_id;
    END IF;
    SELECT * INTO it FROM mbos.items WHERE item_id = p_item_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'mbos: item % not found', p_item_id USING ERRCODE = 'MB404'; END IF;
    IF p_expected_version IS NOT NULL AND it.version <> p_expected_version THEN
        RAISE EXCEPTION 'mbos: item % is at version %, expected %', p_item_id, it.version, p_expected_version
            USING ERRCODE = 'MB409';
    END IF;
    old_state := it.state; old_version := it.version;
    UPDATE mbos.items SET state = p_to_state WHERE item_id = p_item_id RETURNING * INTO it;
    rc := mbos.append_receipt(coalesce(p_extra, '{}') || jsonb_build_object(
        'type', 'ITEM_STATE_CHANGED', 'actor', p_actor, 'intent', p_intent, 'item_id', p_item_id,
        'entity_type', 'item', 'entity_id', p_item_id, 'effect', 'update', 'idempotency_key', p_idempotency_key,
        'provenance_ids', to_jsonb(p_provenance_ids),
        'before_state', jsonb_build_object('state', old_state, 'version', old_version),
        'after_state',  jsonb_build_object('state', it.state, 'version', it.version)));
    RETURN rc.receipt_id;
END $$;

-- Non-state document changes (normalized, research[], economics, scores, recommendation, sources[]).
-- The receipt carries before/after values of the patched keys, so the ledger is the row history.
CREATE FUNCTION mbos.update_item_doc(p_item_id text, p_patch jsonb, p_receipt_type text, p_actor jsonb,
                                     p_intent text, p_provenance_ids text[], p_idempotency_key text,
                                     p_expected_version int DEFAULT NULL, p_extra jsonb DEFAULT '{}')
RETURNS text LANGUAGE plpgsql AS $$
DECLARE it mbos.items; prev mbos.receipts; before jsonb; after jsonb; rc mbos.receipts; k text;
BEGIN
    IF p_receipt_type NOT IN ('ITEM_STATE_CHANGED','SCORE_RECORDED','RECOMMENDATION_RECORDED') THEN
        RAISE EXCEPTION 'mbos: % is not an item-document receipt type', p_receipt_type USING ERRCODE = 'MB004';
    END IF;
    FOR k IN SELECT jsonb_object_keys(p_patch) LOOP
        IF k IN ('item_id','schema_version','type','state','dedup_key','created_at','updated_at',
                 'action_request_ids','approval_ids','receipt_ids','outcome_ids') THEN
            RAISE EXCEPTION 'mbos: % cannot be patched (use transition_item for state)', k USING ERRCODE = 'MB004';
        END IF;
    END LOOP;
    prev := mbos.idempotent_receipt(p_idempotency_key, p_receipt_type);
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.receipt_id; END IF;
    SELECT * INTO it FROM mbos.items WHERE item_id = p_item_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'mbos: item % not found', p_item_id USING ERRCODE = 'MB404'; END IF;
    IF p_expected_version IS NOT NULL AND it.version <> p_expected_version THEN
        RAISE EXCEPTION 'mbos: item % is at version %, expected %', p_item_id, it.version, p_expected_version
            USING ERRCODE = 'MB409';
    END IF;
    SELECT jsonb_object_agg(key, it.doc->key) INTO before FROM jsonb_object_keys(p_patch) key;
    UPDATE mbos.items SET doc = doc || p_patch,
                          category = coalesce(p_patch->>'category', category)
    WHERE item_id = p_item_id RETURNING * INTO it;
    rc := mbos.append_receipt(coalesce(p_extra, '{}') || jsonb_build_object(
        'type', p_receipt_type, 'actor', p_actor, 'intent', p_intent, 'item_id', p_item_id,
        'entity_type', 'item', 'entity_id', p_item_id, 'effect', 'update', 'idempotency_key', p_idempotency_key,
        'provenance_ids', to_jsonb(p_provenance_ids),
        'before_state', jsonb_build_object('version', it.version - 1, 'doc', before),
        'after_state',  jsonb_build_object('version', it.version, 'state', it.state, 'doc', p_patch)));
    RETURN rc.receipt_id;
END $$;

-- ---------------------------------------------------------------------------
-- Action requests
-- ---------------------------------------------------------------------------
CREATE FUNCTION mbos.propose_action(p_areq jsonb, p_actor jsonb, p_intent text, p_idempotency_key text)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE a mbos.action_requests; prev mbos.receipts;
BEGIN
    prev := mbos.idempotent_receipt(p_idempotency_key, 'ACTION_PROPOSED');
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.action_request_id; END IF;
    a := jsonb_populate_record(NULL::mbos.action_requests, p_areq);
    a.action_request_id := coalesce(a.action_request_id, mbos.new_id('areq'));
    a.payload_hash      := coalesce(a.payload_hash, mbos.payload_hash(a.payload));
    a.created_at        := coalesce(a.created_at, now());
    a.on_behalf_of      := 'michael';
    a.tier              := coalesce(a.tier, 0);
    a.status            := 'drafted';
    a.updated_at        := now();
    a.version           := 1;
    INSERT INTO mbos.action_requests SELECT a.*;
    PERFORM mbos.append_receipt(jsonb_build_object(
        'type', 'ACTION_PROPOSED', 'actor', p_actor, 'intent', p_intent, 'item_id', a.item_id,
        'action_request_id', a.action_request_id, 'capability', a.capability, 'payload_hash', a.payload_hash,
        'entity_type', 'action_request', 'entity_id', a.action_request_id, 'effect', 'none',
        'idempotency_key', p_idempotency_key, 'provenance_ids', to_jsonb(a.provenance_ids),
        'after_state', jsonb_build_object('status', a.status, 'tier', a.tier, 'category', a.category,
                                          'reversibility', a.reversibility)));
    RETURN a.action_request_id;
END $$;

-- Generic status move (classification, approval request, execution, failure, freeze, expiry).
-- p_extra may carry receipt fields: approval_id, effector_response, effect, policy_decision_ref,
-- budget_effect, llm_cost, details, tool_name, inputs_hash, artifact_hashes, outcome_id.
CREATE FUNCTION mbos.set_action_status(p_areq_id text, p_to_status text, p_receipt_type text, p_actor jsonb,
                                       p_intent text, p_provenance_ids text[], p_idempotency_key text,
                                       p_extra jsonb DEFAULT '{}', p_tier int DEFAULT NULL)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE a mbos.action_requests; prev mbos.receipts; old_status text; rc mbos.receipts;
BEGIN
    prev := mbos.idempotent_receipt(p_idempotency_key, p_receipt_type);
    IF prev.receipt_id IS NOT NULL THEN
        IF prev.action_request_id IS DISTINCT FROM p_areq_id OR prev.after_state->>'status' IS DISTINCT FROM p_to_status THEN
            RAISE EXCEPTION 'mbos: idempotency key % was used for a different action transition', p_idempotency_key
                USING ERRCODE = 'MB409';
        END IF;
        RETURN prev.receipt_id;
    END IF;
    SELECT * INTO a FROM mbos.action_requests WHERE action_request_id = p_areq_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'mbos: action request % not found', p_areq_id USING ERRCODE = 'MB404'; END IF;
    old_status := a.status;
    UPDATE mbos.action_requests
       SET status = p_to_status, tier = coalesce(p_tier, tier),
           policy_decision_ref = coalesce(p_extra->>'policy_decision_ref', policy_decision_ref)
     WHERE action_request_id = p_areq_id RETURNING * INTO a;
    rc := mbos.append_receipt(coalesce(p_extra, '{}') || jsonb_build_object(
        'type', p_receipt_type, 'actor', p_actor, 'intent', p_intent, 'item_id', a.item_id,
        'action_request_id', a.action_request_id, 'capability', a.capability, 'payload_hash', a.payload_hash,
        'entity_type', 'action_request', 'entity_id', a.action_request_id,
        'idempotency_key', p_idempotency_key, 'provenance_ids', to_jsonb(p_provenance_ids),
        'before_state', jsonb_build_object('status', old_status),
        'after_state',  jsonb_build_object('status', a.status, 'tier', a.tier)));
    RETURN rc.receipt_id;
END $$;

-- ---------------------------------------------------------------------------
-- Approvals: approval row + human provenance + request status + APPROVAL_DECIDED receipt, atomically.
-- ---------------------------------------------------------------------------
CREATE FUNCTION mbos.record_approval(p_appr jsonb, p_actor jsonb, p_intent text, p_idempotency_key text,
                                     p_extra_provenance_ids text[] DEFAULT '{}')
RETURNS text LANGUAGE plpgsql AS $$
DECLARE ap mbos.approvals; a mbos.action_requests; prev mbos.receipts; pid text; new_status text; old_status text;
BEGIN
    prev := mbos.idempotent_receipt(p_idempotency_key, 'APPROVAL_DECIDED');
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.approval_id; END IF;
    ap := jsonb_populate_record(NULL::mbos.approvals, p_appr);
    INSERT INTO mbos.approvals (approval_id, action_request_id, decision, decider, decided_at, channel, auth_context,
                                payload_hash_seen, modifications, hold, reason, scope, expires_at)
    VALUES (coalesce(ap.approval_id, mbos.new_id('appr')), ap.action_request_id, ap.decision, ap.decider,
            coalesce(ap.decided_at, now()), ap.channel, ap.auth_context, ap.payload_hash_seen, ap.modifications,
            ap.hold, ap.reason, coalesce(ap.scope, 'once'), ap.expires_at)
    RETURNING * INTO ap;
    pid := mbos.record_provenance(jsonb_build_object(
        'actor_type', 'human', 'human_actor', ap.decider, 'basis', 'FACT', 'approval_id', ap.approval_id));
    SELECT status INTO old_status FROM mbos.action_requests WHERE action_request_id = ap.action_request_id;
    new_status := CASE ap.decision WHEN 'YES' THEN 'approved' WHEN 'HOLD' THEN 'held' ELSE 'rejected' END;
    -- The request trigger sees the YES approval inserted above; the deferred checks find the receipt below.
    UPDATE mbos.action_requests SET status = new_status WHERE action_request_id = ap.action_request_id
    RETURNING * INTO a;
    PERFORM mbos.append_receipt(jsonb_build_object(
        'type', 'APPROVAL_DECIDED', 'actor', p_actor, 'intent', p_intent, 'item_id', a.item_id,
        'action_request_id', a.action_request_id, 'approval_id', ap.approval_id, 'capability', a.capability,
        'payload_hash', a.payload_hash, 'entity_type', 'approval', 'entity_id', ap.approval_id, 'effect', 'none',
        'idempotency_key', p_idempotency_key,
        'provenance_ids', to_jsonb(ARRAY[pid] || coalesce(p_extra_provenance_ids, '{}')),
        'before_state', jsonb_build_object('status', old_status),
        'after_state',  jsonb_build_object('status', a.status, 'decision', ap.decision, 'scope', ap.scope)));
    RETURN ap.approval_id;
END $$;

-- ---------------------------------------------------------------------------
-- Outcomes and lessons
-- ---------------------------------------------------------------------------
CREATE FUNCTION mbos.record_outcome(p_outcome jsonb, p_actor jsonb, p_intent text, p_idempotency_key text)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE o mbos.outcomes; prev mbos.receipts; a mbos.action_requests; after jsonb;
BEGIN
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

CREATE FUNCTION mbos.record_lesson(p_lesson jsonb, p_actor jsonb, p_intent text, p_idempotency_key text)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE l mbos.lessons; prev mbos.receipts;
BEGIN
    prev := mbos.idempotent_receipt(p_idempotency_key, 'LESSON_RECORDED');
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.entity_id; END IF;
    l := jsonb_populate_record(NULL::mbos.lessons, p_lesson);
    INSERT INTO mbos.lessons (lesson_id, scope, statement, basis, item_id, outcome_ids, evidence,
                              proposed_config_change, supersedes, provenance_ids)
    VALUES (coalesce(l.lesson_id, mbos.new_id('lsn')), l.scope, l.statement, l.basis, l.item_id, l.outcome_ids,
            l.evidence, l.proposed_config_change, l.supersedes, l.provenance_ids)
    RETURNING * INTO l;
    PERFORM mbos.append_receipt(jsonb_build_object(
        'type', 'LESSON_RECORDED', 'actor', p_actor, 'intent', p_intent, 'item_id', l.item_id,
        'entity_type', 'lesson', 'entity_id', l.lesson_id, 'effect', 'create', 'idempotency_key', p_idempotency_key,
        'provenance_ids', to_jsonb(l.provenance_ids),
        'after_state', jsonb_build_object('scope', l.scope, 'basis', l.basis, 'statement', l.statement)));
    RETURN l.lesson_id;
END $$;

-- ---------------------------------------------------------------------------
-- Policy (role policy_admin)
-- ---------------------------------------------------------------------------
CREATE FUNCTION mbos.publish_policy(p_policy jsonb, p_actor jsonb, p_intent text, p_idempotency_key text)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE pol mbos.policy; prev mbos.receipts;
BEGIN
    prev := mbos.idempotent_receipt(p_idempotency_key, 'CONFIG_VERSION_BUMPED');
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.entity_id; END IF;
    pol := jsonb_populate_record(NULL::mbos.policy, p_policy);
    PERFORM pg_advisory_xact_lock(hashtextextended('mbos.policy:' || pol.policy_key, 0));
    INSERT INTO mbos.policy (policy_id, policy_key, version, category, capability, tier, decision, limits,
                             effective_from, created_by, reason, provenance_ids)
    VALUES (coalesce(pol.policy_id, mbos.new_id('pol')), pol.policy_key,
            coalesce(pol.version, (SELECT coalesce(max(version), 0) + 1 FROM mbos.policy WHERE policy_key = pol.policy_key)),
            pol.category, pol.capability, pol.tier, pol.decision, coalesce(pol.limits, '{}'),
            coalesce(pol.effective_from, now()), pol.created_by, pol.reason, pol.provenance_ids)
    RETURNING * INTO pol;
    PERFORM mbos.append_receipt(jsonb_build_object(
        'type', 'CONFIG_VERSION_BUMPED', 'actor', p_actor, 'intent', p_intent, 'entity_type', 'policy',
        'entity_id', pol.policy_id, 'effect', 'create', 'idempotency_key', p_idempotency_key,
        'provenance_ids', to_jsonb(pol.provenance_ids),
        'after_state', jsonb_build_object('policy_key', pol.policy_key, 'version', pol.version,
                                          'decision', pol.decision, 'tier', pol.tier, 'limits', pol.limits)));
    RETURN pol.policy_id;
END $$;

-- ---------------------------------------------------------------------------
-- Budget ledger (role gateway). Fail-closed: no cap => no reservation.
-- Exposure for a category/currency = reserved - released (commits stay spent).
-- ---------------------------------------------------------------------------
CREATE FUNCTION mbos.budget_exposure(p_category text, p_currency text) RETURNS numeric
LANGUAGE sql STABLE AS $$
    SELECT coalesce(sum(CASE kind WHEN 'reserve' THEN amount WHEN 'release' THEN -amount ELSE 0 END), 0)
    FROM mbos.budget_ledger WHERE category = p_category AND currency = p_currency
$$;

CREATE FUNCTION mbos.budget_reserve(p_areq_id text, p_amount numeric, p_currency text, p_cap numeric,
                                    p_actor jsonb, p_intent text, p_provenance_ids text[], p_idempotency_key text)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE a mbos.action_requests; prev mbos.receipts; exposure numeric; e mbos.budget_ledger;
BEGIN
    prev := mbos.idempotent_receipt(p_idempotency_key, 'BUDGET_RESERVED');
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.entity_id; END IF;
    IF p_cap IS NULL THEN
        RAISE EXCEPTION 'mbos: no budget cap supplied — reservation denied (fail-closed)' USING ERRCODE = 'MB006';
    END IF;
    SELECT * INTO a FROM mbos.action_requests WHERE action_request_id = p_areq_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'mbos: action request % not found', p_areq_id USING ERRCODE = 'MB404'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('mbos.budget.cat:' || a.category || ':' || p_currency, 0));
    exposure := mbos.budget_exposure(a.category, p_currency);
    IF exposure + p_amount > p_cap THEN
        RAISE EXCEPTION 'mbos: reserving % % would exceed the % cap % (current exposure %)',
            p_amount, p_currency, a.category, p_cap, exposure USING ERRCODE = 'MB006';
    END IF;
    INSERT INTO mbos.budget_ledger (kind, category, action_request_id, amount, currency, cap_applied, provenance_ids)
    VALUES ('reserve', a.category, a.action_request_id, p_amount, p_currency, p_cap, p_provenance_ids)
    RETURNING * INTO e;
    PERFORM mbos.append_receipt(jsonb_build_object(
        'type', 'BUDGET_RESERVED', 'actor', p_actor, 'intent', p_intent, 'item_id', a.item_id,
        'action_request_id', a.action_request_id, 'capability', a.capability, 'payload_hash', a.payload_hash,
        'entity_type', 'budget_entry', 'entity_id', e.entry_id, 'effect', 'none', 'idempotency_key', p_idempotency_key,
        'provenance_ids', to_jsonb(p_provenance_ids),
        'budget_effect', jsonb_build_object('category', e.category, 'amount', e.amount, 'currency', e.currency),
        'after_state', jsonb_build_object('kind', 'reserve', 'exposure', exposure + p_amount, 'cap', p_cap),
        'details', jsonb_build_object('kind', 'money', 'dry_run', true)));
    RETURN e.entry_id;
END $$;

CREATE FUNCTION mbos.budget_settle(p_reservation_id text, p_kind text, p_amount numeric, p_actor jsonb,
                                   p_intent text, p_provenance_ids text[], p_idempotency_key text)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE res mbos.budget_ledger; a mbos.action_requests; prev mbos.receipts; e mbos.budget_ledger; amt numeric; rtype text;
BEGIN
    IF p_kind NOT IN ('commit','release') THEN
        RAISE EXCEPTION 'mbos: settle kind must be commit or release' USING ERRCODE = 'MB006';
    END IF;
    rtype := CASE p_kind WHEN 'commit' THEN 'BUDGET_COMMITTED' ELSE 'BUDGET_RELEASED' END;
    prev := mbos.idempotent_receipt(p_idempotency_key, rtype);
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.entity_id; END IF;
    SELECT * INTO res FROM mbos.budget_ledger WHERE entry_id = p_reservation_id AND kind = 'reserve';
    IF NOT FOUND THEN RAISE EXCEPTION 'mbos: reservation % not found', p_reservation_id USING ERRCODE = 'MB404'; END IF;
    SELECT * INTO a FROM mbos.action_requests WHERE action_request_id = res.action_request_id;
    amt := coalesce(p_amount, res.amount - (SELECT coalesce(sum(amount), 0) FROM mbos.budget_ledger
                                           WHERE reservation_id = res.entry_id));
    INSERT INTO mbos.budget_ledger (kind, category, action_request_id, reservation_id, amount, currency, provenance_ids)
    VALUES (p_kind, res.category, res.action_request_id, res.entry_id, amt, res.currency, p_provenance_ids)
    RETURNING * INTO e;
    PERFORM mbos.append_receipt(jsonb_build_object(
        'type', rtype, 'actor', p_actor, 'intent', p_intent, 'item_id', a.item_id,
        'action_request_id', a.action_request_id, 'capability', a.capability, 'payload_hash', a.payload_hash,
        'entity_type', 'budget_entry', 'entity_id', e.entry_id, 'effect', 'none', 'idempotency_key', p_idempotency_key,
        'provenance_ids', to_jsonb(p_provenance_ids),
        'budget_effect', jsonb_build_object('category', e.category, 'amount', e.amount, 'currency', e.currency),
        'after_state', jsonb_build_object('kind', p_kind, 'reservation_id', res.entry_id),
        'details', jsonb_build_object('kind', 'money', 'dry_run', true)));
    RETURN e.entry_id;
END $$;
