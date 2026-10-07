-- 0015_card_inputs.sql — READY_QUEUE D-16 (ADR-0011 card enrichment on lane D).
-- Lanes attach enrichment blocks to Items as content-addressed artifacts cited from Item.research[]
-- (field "card.<block>", source_uri "artifact:<sha256>"). Two things lane D adds:
--   1. mbos.append_item_research(): an ATOMIC append to research[]. Writing research[] back through
--      update_item_doc is read-modify-write and silently loses an entry when two lanes enrich the same item
--      concurrently (reproduced: 'card.comps' dropped, only 'card.photos' survived). The append locks the
--      item row first and reads inside the lock, so no entry is lost.
--   2. mbos.v_item_card_inputs: one row per (item, block) — the LATEST entry — joined to the artifact, so the
--      Operator UI reads cards without parsing research[] or touching bytea.

-- Parse JSON bytes without ever raising: one malformed artifact must not break a UI query.
CREATE FUNCTION mbos.try_jsonb(b bytea) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
BEGIN
    RETURN convert_from(b, 'UTF8')::jsonb;
EXCEPTION WHEN others THEN
    RETURN NULL;
END $$;

CREATE FUNCTION mbos.append_item_research(p_item_id text, p_entries jsonb, p_actor jsonb, p_intent text,
                                          p_provenance_ids text[], p_idempotency_key text,
                                          p_receipt_type text DEFAULT 'ITEM_STATE_CHANGED',
                                          p_extra jsonb DEFAULT '{}')
RETURNS text LANGUAGE plpgsql AS $$
DECLARE cur jsonb; prev mbos.receipts;
BEGIN
    IF jsonb_typeof(p_entries) IS DISTINCT FROM 'array' OR jsonb_array_length(p_entries) = 0 THEN
        RAISE EXCEPTION 'mbos: p_entries must be a non-empty JSON array' USING ERRCODE = 'MB004';
    END IF;
    prev := mbos.idempotent_receipt(p_idempotency_key, p_receipt_type);
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.receipt_id; END IF;      -- replay: already appended once
    SELECT coalesce(CASE WHEN jsonb_typeof(doc->'research') = 'array' THEN doc->'research' END, '[]'::jsonb)
      INTO cur FROM mbos.items WHERE item_id = p_item_id FOR UPDATE;          -- lock BEFORE reading
    IF NOT FOUND THEN RAISE EXCEPTION 'mbos: item % not found', p_item_id USING ERRCODE = 'MB404'; END IF;
    RETURN mbos.update_item_doc(p_item_id, jsonb_build_object('research', cur || p_entries), p_receipt_type, p_actor,
                                p_intent, p_provenance_ids, p_idempotency_key, NULL, p_extra);
END $$;

CREATE VIEW mbos.v_item_card_inputs AS
WITH entries AS (
    SELECT i.item_id, i.type AS lane, i.category, i.state, r.entry, r.ord,
           substr(r.entry->>'field', 6) AS block
    FROM mbos.items i,
         jsonb_array_elements(CASE WHEN jsonb_typeof(i.doc->'research') = 'array' THEN i.doc->'research'
                                   ELSE '[]'::jsonb END) WITH ORDINALITY AS r(entry, ord)
    WHERE r.entry->>'field' LIKE 'card.%'
), latest AS (
    SELECT DISTINCT ON (item_id, block) * FROM entries ORDER BY item_id, block, ord DESC
)
SELECT l.item_id, l.lane, l.category, l.state, l.block, l.ord::int AS research_index,
       l.entry->>'finding' AS finding, l.entry->>'basis' AS basis,
       l.entry->>'provenance_id' AS provenance_id, l.entry->>'source_uri' AS source_uri,
       a.sha256 AS artifact_sha256, a.media_type, a.storage, a.location,
       mbos.try_jsonb(a.content) AS data,                 -- NULL for fs-stored blobs: read them with ArtifactStore
       (a.sha256 IS NULL) AS artifact_missing
FROM latest l
LEFT JOIN mbos.artifacts a ON a.sha256 = substr(l.entry->>'source_uri', length('artifact:') + 1)
                          AND l.entry->>'source_uri' LIKE 'artifact:sha256:%';
COMMENT ON VIEW mbos.v_item_card_inputs IS
    'Latest card-enrichment block per (item, block): finding/basis/provenance + artifact JSON (inline). ADR-0011.';

REVOKE ALL ON mbos.v_item_card_inputs FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION mbos.try_jsonb(bytea),
    mbos.append_item_research(text, jsonb, jsonb, text, text[], text, text, jsonb) FROM PUBLIC;
GRANT SELECT ON mbos.v_item_card_inputs TO agent_read, agent_write, gateway, approver, policy_admin;
GRANT EXECUTE ON FUNCTION mbos.try_jsonb(bytea) TO agent_read, agent_write, gateway, approver, policy_admin;
GRANT EXECUTE ON FUNCTION mbos.append_item_research(text, jsonb, jsonb, text, text[], text, text, jsonb)
    TO agent_write, gateway;
