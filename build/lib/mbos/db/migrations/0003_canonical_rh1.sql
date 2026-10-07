-- 0003: ADR-0010 — MBOS-CJSON-1 (RFC 8785 profile) + MBOS-RH-1 receipt row_hash (coordinator ruling F-13/F-14).
-- Functions are a verbatim copy of docs/research/contracts/canonical/mbos_canonical.sql (tests check both agree).
-- Pre-ADR-0010 chains used a different formula; no production chain exists (nothing deployed), so this
-- migration refuses to run over existing receipts instead of rewriting history. Recreate dev databases.
DO $$ BEGIN IF EXISTS (SELECT 1 FROM mbos.receipts) THEN
  RAISE EXCEPTION 'mbos 0003: receipts already exist under the pre-ADR-0010 formula; recreate this dev database';
END IF; END $$;
-- MBOS-CJSON-1 / MBOS-RH-1 reference implementation for PostgreSQL >= 13 (ADR-0010). Normative twin of
-- mbos_canonical.py; both must reproduce vectors.json byte-for-byte. Lane D (Agent 04) owns the production
-- ledger and installs these functions in its schema; nothing here depends on table layout.


-- ECMAScript Number.prototype.toString of the IEEE-754 double nearest to the JSON number (RFC 8785 §3.2.2.3).
CREATE OR REPLACE FUNCTION mbos.cjson_number(j jsonb) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE SET extra_float_digits = 1 AS $$
DECLARE
    f float8 := (j #>> '{}')::float8;
    s text; mant text; ip text; fp text; digits text; ex int := 0; n int; k int; lead int; e int; r text;
BEGIN
    IF f = 0 THEN RETURN '0'; END IF;
    IF f = trunc(f) AND abs(f) > 9007199254740991 THEN
        RAISE EXCEPTION 'MBOS-CJSON-1: integral value % outside +/-(2^53-1)', j #>> '{}';
    END IF;
    s := abs(f)::text;                         -- shortest round-trip digits (extra_float_digits >= 1)
    IF position('e' IN s) > 0 THEN
        mant := split_part(s, 'e', 1); ex := split_part(s, 'e', 2)::int;
    ELSE
        mant := s;
    END IF;
    ip := split_part(mant, '.', 1); fp := split_part(mant, '.', 2);
    digits := ip || fp; n := length(ip) + ex;  -- value = 0.<digits> * 10^n
    lead := length(digits) - length(ltrim(digits, '0'));
    digits := rtrim(ltrim(digits, '0'), '0'); n := n - lead; k := length(digits);
    IF k <= n AND n <= 21 THEN r := digits || repeat('0', n - k);
    ELSIF 0 < n AND n <= 21 THEN r := substr(digits, 1, n) || '.' || substr(digits, n + 1);
    ELSIF -6 < n AND n <= 0 THEN r := '0.' || repeat('0', -n) || digits;
    ELSE
        e := n - 1;
        r := substr(digits, 1, 1) || CASE WHEN k > 1 THEN '.' || substr(digits, 2) ELSE '' END
             || 'e' || CASE WHEN e > 0 THEN '+' ELSE '-' END || abs(e)::text;
    END IF;
    RETURN CASE WHEN f < 0 THEN '-' || r ELSE r END;
END $$;

CREATE OR REPLACE FUNCTION mbos.cjson(j jsonb) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE AS $$
DECLARE t text := jsonb_typeof(j); k text; v jsonb; parts text[] := '{}';
BEGIN
    IF t = 'object' THEN
        FOR k, v IN SELECT key, value FROM jsonb_each(j) ORDER BY key COLLATE "C" LOOP
            IF EXISTS (SELECT 1 FROM regexp_split_to_table(k, '') c WHERE ascii(c) > 65535) THEN
                RAISE EXCEPTION 'MBOS-CJSON-1: member name % contains a non-BMP character', k;
            END IF;
            parts := parts || (to_json(k)::text || ':' || mbos.cjson(v));
        END LOOP;
        RETURN '{' || array_to_string(parts, ',') || '}';
    ELSIF t = 'array' THEN
        FOR v IN SELECT value FROM jsonb_array_elements(j) WITH ORDINALITY AS a(value, i) ORDER BY i LOOP
            parts := parts || mbos.cjson(v);
        END LOOP;
        RETURN '[' || array_to_string(parts, ',') || ']';
    ELSIF t = 'string' THEN
        RETURN to_json(j #>> '{}')::text;      -- same escapes as JSON.stringify / Python json.dumps
    ELSIF t = 'number' THEN
        RETURN mbos.cjson_number(j);
    ELSE
        RETURN j::text;                        -- true | false | null
    END IF;
END $$;

CREATE OR REPLACE FUNCTION mbos.cjson_sha256(j jsonb) RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT 'sha256:' || encode(sha256(convert_to(mbos.cjson(j), 'UTF8')), 'hex')
$$;

-- MBOS-RH-1: D = receipt document minus row_hash, top-level nulls dropped except prev_hash (always present).
CREATE OR REPLACE FUNCTION mbos.rh1_hash_document(doc jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT coalesce((SELECT jsonb_object_agg(key, value) FROM jsonb_each(doc - 'row_hash' - 'prev_hash')
                     WHERE value <> 'null'::jsonb), '{}'::jsonb)
           || jsonb_build_object('prev_hash', doc -> 'prev_hash')
$$;

CREATE OR REPLACE FUNCTION mbos.rh1_row_hash(doc jsonb) RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT mbos.cjson_sha256(mbos.rh1_hash_document(doc))
$$;

-- The spine's receipts store the document minus seq / prev_hash / row_hash in `body`; MBOS-RH-1 hashes the
-- full document D = body (top-level nulls dropped) + seq + prev_hash.
CREATE OR REPLACE FUNCTION mbos.receipt_row_hash(p_seq bigint, p_body jsonb, p_prev text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT mbos.rh1_row_hash(p_body || jsonb_build_object('seq', p_seq, 'prev_hash', p_prev))
$$;
