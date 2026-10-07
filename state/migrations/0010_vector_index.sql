-- 0010_vector_index.sql — READY_QUEUE D-08 (acceptance D3): pgvector as a REBUILDABLE index, never truth.
-- item_embeddings is a projection of mbos.items: drop it, rebuild it, and queries return identical results.
-- Not a ledger and not receipted: it holds nothing that cannot be regenerated from the receipted Item rows.
-- pgvector is not a trusted extension: the superuser bootstrap creates it in schema mbos_ext
-- (bootstrap.sh); this migration refuses to run without it.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace
                   WHERE e.extname = 'vector' AND n.nspname = 'mbos_ext') THEN
        RAISE EXCEPTION 'mbos: pgvector missing — run bootstrap.sh (superuser: CREATE EXTENSION vector WITH SCHEMA mbos_ext)';
    END IF;
END $$;

CREATE TABLE mbos.item_embeddings (
    item_id       text NOT NULL REFERENCES mbos.items,
    model_id      text NOT NULL,
    model_version text NOT NULL,
    content_hash  text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),  -- MBOS-CJSON-1 of the embedded text
    embedding     mbos_ext.vector(256) NOT NULL,
    embedded_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (item_id, model_id, model_version)
);
COMMENT ON TABLE mbos.item_embeddings IS
    'Rebuildable similarity index (ADR-0001: pgvector is an index, not truth). Each row is tied to its source by '
    'item_id + content_hash; stale rows are detectable and the whole table can be dropped and rebuilt.';
CREATE INDEX item_embeddings_hnsw ON mbos.item_embeddings
    USING hnsw (embedding mbos_ext.vector_cosine_ops);

-- k nearest items to a vector (cosine distance), for one embedding model.
CREATE FUNCTION mbos.similar_items(p_embedding mbos_ext.vector, p_model_id text, p_model_version text, p_k int DEFAULT 10)
RETURNS TABLE (item_id text, distance float8)
LANGUAGE sql STABLE AS $$
    SELECT e.item_id, e.embedding OPERATOR(mbos_ext.<=>) p_embedding
    FROM mbos.item_embeddings e
    WHERE e.model_id = p_model_id AND e.model_version = p_model_version
    ORDER BY e.embedding OPERATOR(mbos_ext.<=>) p_embedding, e.item_id
    LIMIT p_k
$$;

REVOKE ALL ON mbos.item_embeddings FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION mbos.similar_items(mbos_ext.vector, text, text, int) FROM PUBLIC;
GRANT SELECT ON mbos.item_embeddings TO agent_read, agent_write, gateway, approver, policy_admin;
GRANT INSERT, UPDATE ON mbos.item_embeddings TO agent_write;      -- refresh; drop/rebuild is owner maintenance
GRANT EXECUTE ON FUNCTION mbos.similar_items(mbos_ext.vector, text, text, int)
    TO agent_read, agent_write, gateway, approver, policy_admin;
