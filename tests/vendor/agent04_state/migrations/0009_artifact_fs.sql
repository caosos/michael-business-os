-- 0009_artifact_fs.sql — READY_QUEUE D-07: filesystem artifact store; mbos.artifacts stays the index.
-- A storage='fs' row's location is forced to the canonical content-addressed path derived from its own hash,
-- so an index row can never point at an arbitrary file. Paths are relative to $MBOS_ARTIFACT_ROOT
-- (relocatable; restore drills point at the backup copy).

CREATE FUNCTION mbos.artifact_fs_path(p_sha256 text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT 'sha256/' || substr(h, 1, 2) || '/' || substr(h, 3, 2) || '/' || h
    FROM (SELECT substr(p_sha256, 8) AS h) x
$$;

ALTER TABLE mbos.artifacts
    ADD CONSTRAINT artifacts_fs_canonical_location CHECK (storage <> 'fs' OR location = mbos.artifact_fs_path(sha256));

-- Index a file the store has already written and verified. Idempotent; an existing row is never replaced.
CREATE FUNCTION mbos.register_artifact(p_sha256 text, p_media_type text, p_byte_size bigint) RETURNS text
LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO mbos.artifacts (sha256, media_type, byte_size, storage, location)
    VALUES (p_sha256, p_media_type, p_byte_size, 'fs', mbos.artifact_fs_path(p_sha256))
    ON CONFLICT (sha256) DO NOTHING;
    RETURN p_sha256;
END $$;

REVOKE EXECUTE ON FUNCTION mbos.artifact_fs_path(text), mbos.register_artifact(text, text, bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION mbos.artifact_fs_path(text) TO agent_read, agent_write, gateway, approver, policy_admin;
GRANT EXECUTE ON FUNCTION mbos.register_artifact(text, text, bigint) TO agent_write, gateway;
