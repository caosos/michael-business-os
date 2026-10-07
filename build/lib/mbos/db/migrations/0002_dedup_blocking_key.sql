-- 0002: dedup_key is a BLOCKING key (Agent 02 ADR-02-0201: category|priceband|geocell), not an identity.
-- Equal keys only nominate candidates; the Deduper decides. Identity is (source, source_listing_id).
ALTER TABLE mbos.items DROP CONSTRAINT items_dedup_key_key;
CREATE INDEX items_dedup_key_idx ON mbos.items (dedup_key);
CREATE INDEX items_sources_gin ON mbos.items USING gin ((body->'sources') jsonb_path_ops);
