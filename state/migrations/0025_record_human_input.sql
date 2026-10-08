-- 0025_record_human_input.sql — READY_QUEUE D-30 (Michael's typed inputs through the owner UI login).
--   * mbos.record_human_input(item_id, kind, key, value, note, actor, provenance_ids, idempotency_key): SECURITY DEFINER, owner_channel
--     session AND a human actor with an id AND provenance_ids[1] a human provenance naming that same human. kind:
--       scope_override  key '<rehab|job>.<field>' (fields as lane C reads) -> entry field 'scope_override:<key>', basis INFER
--       quote           key 'amount_usd'                                   -> entry field 'quote:amount_usd', basis FACT
--     Entry {finding, field, value, basis, source_uri 'human:<id>', provenance_id, entered_by}; written through append_item_research
--     (atomic, receipted ITEM_STATE_CHANGED, idempotent). Numbers must be finite, >= 0 and <= 10,000,000 (quote > 0, <= 1,000,000).
--     Refusals: 42501 (role/actor) or MB004 (shape).
--   * The 0024 guard now covers 'scope_override:' and 'quote:' entries as well as 'attestation:' (only the definer, i.e. the table owner,
--     may add them).

CREATE OR REPLACE FUNCTION mbos._attestation_count(p_doc jsonb) RETURNS int
LANGUAGE sql IMMUTABLE AS $$
    SELECT count(*)::int FROM jsonb_array_elements(CASE WHEN jsonb_typeof(p_doc->'research') = 'array' THEN p_doc->'research'
                                                        ELSE '[]'::jsonb END) e
    WHERE jsonb_typeof(e) = 'object' AND (e->>'field' LIKE 'attestation:%' OR e->>'field' LIKE 'scope\_override:%'
                                          OR e->>'field' LIKE 'quote:%')
$$;

CREATE FUNCTION mbos.record_human_input(p_item_id text, p_kind text, p_key text, p_value jsonb, p_note text, p_actor jsonb,
                                        p_provenance_ids text[], p_idempotency_key text) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, mbos AS $$
DECLARE prev mbos.receipts; key text := btrim(coalesce(p_key, '')); note text := btrim(coalesce(p_note, '')); who text; pid text;
        fld text; basis text; blk text; fname text; ok boolean := false; entry jsonb;
BEGIN
    IF NOT pg_has_role(session_user, 'owner_channel', 'MEMBER') THEN
        RAISE EXCEPTION 'mbos: role % may not record a human input (owner_channel only)', session_user USING ERRCODE = '42501';
    END IF;
    IF p_actor->>'type' IS DISTINCT FROM 'human' OR coalesce(btrim(p_actor->>'id'), '') = '' THEN
        RAISE EXCEPTION 'mbos: a human input is recorded only by a human (actor.type human with an id), got actor %', p_actor
            USING ERRCODE = '42501';
    END IF;
    who := btrim(p_actor->>'id');
    IF note = '' OR length(note) > 2000 THEN
        RAISE EXCEPTION 'mbos: a human input needs a note (up to 2000 characters)' USING ERRCODE = 'MB004';
    END IF;
    IF p_kind = 'scope_override' THEN
        blk := split_part(key, '.', 1); fname := split_part(key, '.', 2);
        IF key !~ '^[a-z]+\.[a-z_]+$' OR NOT ((blk = 'rehab' AND fname IN ('parts_cost', 'labor_hours', 'admin_hours', 'required_skills'))
             OR (blk = 'job' AND fname IN ('labor_hours', 'materials_cost', 'admin_hours', 'required_skills'))) THEN
            RAISE EXCEPTION 'mbos: scope_override key must be rehab.{parts_cost,labor_hours,admin_hours,required_skills} or job.{labor_hours,materials_cost,admin_hours,required_skills}, got %', key
                USING ERRCODE = 'MB004';
        END IF;
        IF fname = 'required_skills' THEN
            ok := jsonb_typeof(p_value) = 'array' AND jsonb_array_length(p_value) BETWEEN 1 AND 20
                  AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(p_value) s
                                  WHERE jsonb_typeof(s) <> 'string' OR btrim(s #>> '{}') = '' OR length(s #>> '{}') > 60);
        ELSE
            ok := jsonb_typeof(p_value) = 'number' AND (p_value #>> '{}')::numeric BETWEEN 0 AND 10000000;
        END IF;
        fld := 'scope_override:' || key; basis := 'INFER';
    ELSIF p_kind = 'quote' THEN
        IF key <> 'amount_usd' THEN
            RAISE EXCEPTION 'mbos: quote key must be amount_usd, got %', key USING ERRCODE = 'MB004';
        END IF;
        ok := jsonb_typeof(p_value) = 'number' AND (p_value #>> '{}')::numeric > 0 AND (p_value #>> '{}')::numeric <= 1000000;
        fld := 'quote:amount_usd'; basis := 'FACT';
    ELSE
        RAISE EXCEPTION 'mbos: human input kind must be scope_override or quote, got %', p_kind USING ERRCODE = 'MB004';
    END IF;
    IF NOT ok THEN
        RAISE EXCEPTION 'mbos: value % is not valid for % %', p_value, p_kind, key USING ERRCODE = 'MB004';
    END IF;
    pid := p_provenance_ids[1];
    IF pid IS NULL OR NOT EXISTS (SELECT 1 FROM mbos.provenance WHERE provenance_id = pid AND actor_type = 'human' AND human_actor = who) THEN
        RAISE EXCEPTION 'mbos: provenance_ids[1] must be a human provenance record naming %', who USING ERRCODE = 'MB004';
    END IF;
    prev := mbos.idempotent_receipt(p_idempotency_key, 'ITEM_STATE_CHANGED');
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.receipt_id; END IF;
    entry := jsonb_build_object('finding', note, 'field', fld, 'value', p_value, 'basis', basis,
                                'source_uri', 'human:' || who, 'provenance_id', pid, 'entered_by', who);
    RETURN mbos.append_item_research(p_item_id, jsonb_build_array(entry), p_actor, who || ' recorded ' || fld,
                                     p_provenance_ids, p_idempotency_key);
END $$;

REVOKE EXECUTE ON FUNCTION mbos.record_human_input(text, text, text, jsonb, text, jsonb, text[], text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION mbos.record_human_input(text, text, text, jsonb, text, jsonb, text[], text) TO owner_channel;
