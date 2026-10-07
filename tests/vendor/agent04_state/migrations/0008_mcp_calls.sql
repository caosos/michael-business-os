-- 0008_mcp_calls.sql — READY_QUEUE D-06: audit log for the State MCP server (ADR-0003: the only agent write path).
-- One row per tool call, whatever the outcome. A successful WRITE call is logged in the same transaction as
-- its state change, and the database refuses the row unless it links >= 1 existing receipt — so a write call
-- can never succeed without a receipt. Refused / failed calls change nothing; their row records why.

CREATE TABLE mbos.mcp_calls (
    seq           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts            timestamptz NOT NULL DEFAULT now(),
    agent_id      text NOT NULL,            -- caller identity from the server's environment, never from arguments
    profile       text NOT NULL CHECK (profile IN ('agent','operator')),
    tool          text NOT NULL,
    tool_kind     text NOT NULL CHECK (tool_kind IN ('read','write')),
    args_hash     text NOT NULL CHECK (args_hash ~ '^sha256:[0-9a-f]{64}$'),   -- MBOS-CJSON-1 of the arguments
    outcome       text NOT NULL CHECK (outcome IN ('ok','replayed','refused','error')),
    error_code    text,
    error         text,
    provenance_id text REFERENCES mbos.provenance,
    receipt_ids   text[] NOT NULL DEFAULT '{}',
    CONSTRAINT mcp_write_is_receipted CHECK (
        tool_kind = 'read' OR outcome NOT IN ('ok','replayed') OR cardinality(receipt_ids) >= 1),
    CONSTRAINT mcp_failure_has_reason CHECK (outcome IN ('ok','replayed') OR error IS NOT NULL)
);
CREATE INDEX mcp_calls_agent_ts_idx ON mbos.mcp_calls (agent_id, ts);
SELECT mbos.make_append_only('mbos.mcp_calls');

CREATE FUNCTION mbos.mcp_calls_check_receipts() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE missing text[];
BEGIN
    SELECT array_agg(r) INTO missing FROM unnest(NEW.receipt_ids) r
    WHERE NOT EXISTS (SELECT 1 FROM mbos.receipts x WHERE x.receipt_id = r);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'mbos: mcp call cites unknown receipts %', missing USING ERRCODE = 'MB003';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER aa_mcp_calls_check BEFORE INSERT ON mbos.mcp_calls
    FOR EACH ROW EXECUTE FUNCTION mbos.mcp_calls_check_receipts();

REVOKE ALL ON mbos.mcp_calls FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION mbos.mcp_calls_check_receipts() FROM PUBLIC;
GRANT SELECT ON mbos.mcp_calls TO agent_read, agent_write, gateway, approver, policy_admin;
GRANT INSERT ON mbos.mcp_calls TO agent_write, approver;
