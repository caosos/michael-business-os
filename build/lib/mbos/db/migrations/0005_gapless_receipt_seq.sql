-- 0005: gapless receipt seq (finding by Agent 06, 2026-10-07). seq came from nextval(), which is not rolled back,
-- so a rolled-back receipt transaction left a gap: links stayed intact but the ADR-0010 reference
-- verify_chain ("gap before seq N") and mbos.verify_chain disagreed. Now seq = max(seq)+1 under the chain lock
-- (the lock is held to commit, so this is gapless and race-free), and verify_chain checks contiguity too.
CREATE OR REPLACE FUNCTION mbos.receipts_chain() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    missing text;
    last_seq bigint;
    last_hash text;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'mbos: receipts must be written under READ COMMITTED (got %)', current_setting('transaction_isolation');
    END IF;
    PERFORM pg_advisory_xact_lock(hashtext('mbos.receipts.chain'));
    SELECT p INTO missing
      FROM jsonb_array_elements_text(NEW.body->'provenance_ids') AS p
     WHERE NOT EXISTS (SELECT 1 FROM mbos.provenance v WHERE v.provenance_id = p)
     LIMIT 1;
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'mbos: no receipt without provenance — % does not exist', missing;
    END IF;
    SELECT r.seq, r.row_hash INTO last_seq, last_hash FROM mbos.receipts r ORDER BY r.seq DESC LIMIT 1;
    NEW.seq := coalesce(last_seq, 0) + 1;
    NEW.prev_hash := last_hash;
    NEW.row_hash := mbos.receipt_row_hash(NEW.seq, NEW.body, NEW.prev_hash);
    RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION mbos.verify_chain()
RETURNS TABLE (ok boolean, checked bigint, first_bad_seq bigint, reason text)
LANGUAGE plpgsql STABLE AS $$
DECLARE
    r record;
    expected_prev text := NULL;
    expected_seq bigint := NULL;
    n bigint := 0;
BEGIN
    FOR r IN SELECT seq, body, prev_hash, row_hash FROM mbos.receipts ORDER BY seq LOOP
        n := n + 1;
        IF expected_seq IS NOT NULL AND r.seq <> expected_seq THEN
            RETURN QUERY SELECT false, n, r.seq, 'gap before seq (seq is not contiguous)'; RETURN;
        END IF;
        IF r.prev_hash IS DISTINCT FROM expected_prev THEN
            RETURN QUERY SELECT false, n, r.seq, 'prev_hash does not link to previous row_hash'; RETURN;
        END IF;
        IF r.row_hash <> mbos.receipt_row_hash(r.seq, r.body, r.prev_hash) THEN
            RETURN QUERY SELECT false, n, r.seq, 'row_hash does not match row content'; RETURN;
        END IF;
        expected_prev := r.row_hash;
        expected_seq := r.seq + 1;
    END LOOP;
    RETURN QUERY SELECT true, n, NULL::bigint, NULL::text;
END $$;
