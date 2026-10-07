-- 0014_item_doc_entity.sql — READY_QUEUE D-14 (03 C-12): update_item_doc keeps a caller-supplied
-- entity_type/entity_id when entity_type is 'scorecard' (scr_…) or 'recommendation' (rec_…), so a scorecard or
-- recommendation is findable in the ledger by its own id. item_id stays on the receipt (the same-transaction
-- invariant and item history are unchanged); any other caller-supplied entity is still overridden to the item.

CREATE OR REPLACE FUNCTION mbos.update_item_doc(p_item_id text, p_patch jsonb, p_receipt_type text, p_actor jsonb,
                                     p_intent text, p_provenance_ids text[], p_idempotency_key text,
                                     p_expected_version int DEFAULT NULL, p_extra jsonb DEFAULT '{}')
RETURNS text LANGUAGE plpgsql AS $$
DECLARE it mbos.items; prev mbos.receipts; before jsonb; after jsonb; rc mbos.receipts; k text;
        ent_type text := 'item'; ent_id text := p_item_id;
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
    -- D-14: a scorecard / recommendation write may name its own entity so the ledger is queryable by its id.
    IF p_extra->>'entity_type' IN ('scorecard', 'recommendation') THEN
        IF NOT (p_extra->>'entity_type' = 'scorecard' AND p_extra->>'entity_id' ~ '^scr_[0-9A-HJKMNP-TV-Z]{26}$')
           AND NOT (p_extra->>'entity_type' = 'recommendation' AND p_extra->>'entity_id' ~ '^rec_[0-9A-HJKMNP-TV-Z]{26}$') THEN
            RAISE EXCEPTION 'mbos: entity_id % is not a valid % id', p_extra->>'entity_id', p_extra->>'entity_type'
                USING ERRCODE = 'MB004';
        END IF;
        ent_type := p_extra->>'entity_type';
        ent_id := p_extra->>'entity_id';
    END IF;
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
        'entity_type', ent_type, 'entity_id', ent_id, 'effect', 'update', 'idempotency_key', p_idempotency_key,
        'provenance_ids', to_jsonb(p_provenance_ids),
        'before_state', jsonb_build_object('version', it.version - 1, 'doc', before),
        'after_state',  jsonb_build_object('version', it.version, 'state', it.state, 'doc', p_patch)));
    RETURN rc.receipt_id;
END $$;
