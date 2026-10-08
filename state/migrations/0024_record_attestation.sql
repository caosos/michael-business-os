-- 0024_record_attestation.sql — READY_QUEUE D-29 (Michael's attestation through the owner UI login).
--   mbos_operator_ui (owner_channel) had no way to confirm evidence: append_item_research is agent_write/gateway only.
--     * mbos.record_attestation(item_id, evidence_key, note, actor, provenance_ids, idempotency_key): SECURITY DEFINER, owner_channel
--       session AND a human actor with an id AND a human provenance record naming that same human (provenance_ids[1]). Writes ONE
--       research entry {field 'attestation:<key>', basis FACT, source_uri 'human:<id>', provenance_id} through append_item_research
--       (atomic, receipted ITEM_STATE_CHANGED, idempotent on the key). Refusals are 42501 (role/actor) or MB004 (shape).
--     * Guard: an item write that adds an 'attestation:' research entry is refused unless it runs as the items table owner, i.e. inside
--       the definer function. agent_write keeps append_item_research / update_item_doc for lane enrichments but cannot forge one.
--   Lane C reads the entry from Item.research (field prefix 'attestation:'), unchanged.

CREATE FUNCTION mbos._attestation_count(p_doc jsonb) RETURNS int
LANGUAGE sql IMMUTABLE AS $$
    SELECT count(*)::int FROM jsonb_array_elements(CASE WHEN jsonb_typeof(p_doc->'research') = 'array' THEN p_doc->'research'
                                                        ELSE '[]'::jsonb END) e
    WHERE jsonb_typeof(e) = 'object' AND e->>'field' LIKE 'attestation:%'
$$;

CREATE FUNCTION mbos.items_attestation_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE before_n int := 0;
BEGIN
    IF TG_OP = 'UPDATE' THEN before_n := mbos._attestation_count(OLD.doc); END IF;
    IF mbos._attestation_count(NEW.doc) > before_n
       AND current_user::text IS DISTINCT FROM (SELECT relowner::regrole::text FROM pg_class WHERE oid = 'mbos.items'::regclass) THEN
        RAISE EXCEPTION 'mbos: attestation research entries are written only by mbos.record_attestation (owner channel); role % refused',
            session_user USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER ab_items_attestation_guard BEFORE INSERT OR UPDATE ON mbos.items
    FOR EACH ROW EXECUTE FUNCTION mbos.items_attestation_guard();

CREATE FUNCTION mbos.record_attestation(p_item_id text, p_evidence_key text, p_note text, p_actor jsonb,
                                        p_provenance_ids text[], p_idempotency_key text) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, mbos AS $$
DECLARE prev mbos.receipts; key text := btrim(coalesce(p_evidence_key, '')); note text := btrim(coalesce(p_note, '')); who text; pid text; entry jsonb;
BEGIN
    IF NOT pg_has_role(session_user, 'owner_channel', 'MEMBER') THEN
        RAISE EXCEPTION 'mbos: role % may not record an attestation (owner_channel only)', session_user USING ERRCODE = '42501';
    END IF;
    IF p_actor->>'type' IS DISTINCT FROM 'human' OR coalesce(btrim(p_actor->>'id'), '') = '' THEN
        RAISE EXCEPTION 'mbos: an attestation is recorded only by a human (actor.type human with an id), got actor %', p_actor
            USING ERRCODE = '42501';
    END IF;
    who := btrim(p_actor->>'id');
    IF key = '' OR note = '' OR key !~ '^[A-Za-z0-9_.-]{1,80}$' OR length(note) > 2000 THEN
        RAISE EXCEPTION 'mbos: attestation needs an evidence_key ([A-Za-z0-9_.-], up to 80) and a note (up to 2000 characters)'
            USING ERRCODE = 'MB004';
    END IF;
    pid := p_provenance_ids[1];
    IF pid IS NULL OR NOT EXISTS (SELECT 1 FROM mbos.provenance WHERE provenance_id = pid AND actor_type = 'human' AND human_actor = who) THEN
        RAISE EXCEPTION 'mbos: provenance_ids[1] must be a human provenance record naming %', who USING ERRCODE = 'MB004';
    END IF;
    prev := mbos.idempotent_receipt(p_idempotency_key, 'ITEM_STATE_CHANGED');
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.receipt_id; END IF;
    entry := jsonb_build_object('finding', note, 'field', 'attestation:' || key, 'basis', 'FACT',
                                'source_uri', 'human:' || who, 'provenance_id', pid);
    RETURN mbos.append_item_research(p_item_id, jsonb_build_array(entry), p_actor, who || ' confirmed evidence ' || key,
                                     p_provenance_ids, p_idempotency_key);
END $$;

REVOKE EXECUTE ON FUNCTION mbos._attestation_count(jsonb), mbos.items_attestation_guard(),
    mbos.record_attestation(text, text, text, jsonb, text[], text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION mbos._attestation_count(jsonb) TO PUBLIC;
GRANT EXECUTE ON FUNCTION mbos.record_attestation(text, text, text, jsonb, text[], text) TO owner_channel;
