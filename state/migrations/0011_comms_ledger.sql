-- 0011_comms_ledger.sql — READY_QUEUE D-10: adopt Agent 06's consent ledger + DNC scrub store (F-07,
-- origin/research/agent-06-communications:comms_spec/sql/0001_comms_ledger.sql) under lane D (R1: one DDL owner).
-- Table, column, function and trigger names are kept identical so 06's comms_spec.ledger works unchanged
-- (its ensure_schema() becomes a no-op check on a lane-D database). Lane D adds:
--   * consent_events / dnc_scrubs.receipt_id is a real FK, and the receipt must be written in the SAME
--     transaction (GRANT_CREATED / GRANT_REVOKED for that contact_ref) — no consent change without a receipt;
--   * fail-safe asymmetry: only `gateway` (comms intake / effector side) may record what ENABLES a send
--     (consent granted, DNC scrub clear); anyone with write access may record a revocation, STOP or listing;
--   * raw contact values: column-level SELECT so only `gateway` can read contacts.value.

CREATE SCHEMA IF NOT EXISTS mbos_comms;

CREATE FUNCTION mbos_comms.reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'mbos_comms.% is insert-only (% rejected)', TG_TABLE_NAME, TG_OP USING ERRCODE = 'MB001';
END $$;

CREATE TABLE mbos_comms.contacts (
    contact_ref  text PRIMARY KEY CHECK (contact_ref ~ '^cref_[0-9A-HJKMNP-TV-Z]{26}$'),
    subject_ref  text NOT NULL,                       -- listing URL / party ref the planner uses as recipient.ref
    channel      text NOT NULL CHECK (channel IN ('sms', 'email', 'voice')),
    value        text NOT NULL,                       -- RAW contact value: stays here, never copied
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (channel, value)
);
CREATE INDEX contacts_subject_idx ON mbos_comms.contacts (subject_ref, channel);

CREATE TABLE mbos_comms.consent_events (
    seq          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    contact_ref  text NOT NULL REFERENCES mbos_comms.contacts (contact_ref),
    event        text NOT NULL CHECK (event IN ('granted', 'revoked')),
    basis        text NOT NULL,
    evidence_uri text,
    recorded_at  timestamptz NOT NULL,
    receipt_id   text NOT NULL UNIQUE REFERENCES mbos.receipts (receipt_id)
);
CREATE INDEX consent_events_contact_idx ON mbos_comms.consent_events (contact_ref, seq);

CREATE TABLE mbos_comms.dnc_scrubs (
    seq          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    contact_ref  text NOT NULL REFERENCES mbos_comms.contacts (contact_ref),
    scrubbed_at  timestamptz NOT NULL,
    listed       boolean NOT NULL,
    source       text NOT NULL,
    receipt_id   text NOT NULL UNIQUE REFERENCES mbos.receipts (receipt_id)
);
CREATE INDEX dnc_scrubs_contact_idx ON mbos_comms.dnc_scrubs (contact_ref, seq);

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['contacts', 'consent_events', 'dnc_scrubs'] LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON mbos_comms.%I FOR EACH ROW '
                       'EXECUTE FUNCTION mbos_comms.reject_mutation()', t || '_insert_only', t);
        EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON mbos_comms.%I FOR EACH STATEMENT '
                       'EXECUTE FUNCTION mbos_comms.reject_mutation()', t || '_no_truncate', t);
    END LOOP;
END $$;

-- "Enabling" = consent granted, or DNC scrub clear. Fields are read through jsonb so one function serves both tables.
CREATE FUNCTION mbos_comms.is_enabling(tbl text, rec jsonb) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE tbl WHEN 'consent_events' THEN rec->>'event' = 'granted' ELSE (rec->>'listed')::boolean = false END
$$;

-- What enables a send needs the gateway; what stops one is always allowed.
CREATE FUNCTION mbos_comms.enabling_event_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF mbos_comms.is_enabling(TG_TABLE_NAME, to_jsonb(NEW))
       AND NOT (pg_has_role(current_user, 'gateway', 'MEMBER') OR pg_has_role(current_user, 'mbos_owner', 'MEMBER')) THEN
        RAISE EXCEPTION 'mbos_comms: role % may record revocations/listings only; % that enables sending needs gateway',
            current_user, TG_TABLE_NAME USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END $$;

-- The cited receipt must be this transaction's consent/DNC receipt for this contact, in the right direction
-- (enabling = GRANT_CREATED; revocation / listing = GRANT_REVOKED).
CREATE FUNCTION mbos_comms.require_same_tx_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE want text; got text;
BEGIN
    want := CASE WHEN mbos_comms.is_enabling(TG_TABLE_NAME, to_jsonb(NEW)) THEN 'GRANT_CREATED' ELSE 'GRANT_REVOKED' END;
    SELECT r.type INTO got FROM mbos.receipts r
    WHERE r.receipt_id = NEW.receipt_id AND r.tx_id = pg_current_xact_id() AND r.entity_id = NEW.contact_ref;
    IF got IS NULL THEN
        RAISE EXCEPTION 'mbos_comms: % row must cite a receipt for % written in this transaction',
            TG_TABLE_NAME, NEW.contact_ref USING ERRCODE = 'MB003';
    END IF;
    IF got <> want THEN
        RAISE EXCEPTION 'mbos_comms: % event needs a % receipt, got %', TG_TABLE_NAME, want, got USING ERRCODE = 'MB003';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER aa_consent_enabling_guard BEFORE INSERT ON mbos_comms.consent_events
    FOR EACH ROW EXECUTE FUNCTION mbos_comms.enabling_event_guard();
CREATE TRIGGER ab_consent_receipt BEFORE INSERT ON mbos_comms.consent_events
    FOR EACH ROW EXECUTE FUNCTION mbos_comms.require_same_tx_receipt();
CREATE TRIGGER aa_dnc_enabling_guard BEFORE INSERT ON mbos_comms.dnc_scrubs
    FOR EACH ROW EXECUTE FUNCTION mbos_comms.enabling_event_guard();
CREATE TRIGGER ab_dnc_receipt BEFORE INSERT ON mbos_comms.dnc_scrubs
    FOR EACH ROW EXECUTE FUNCTION mbos_comms.require_same_tx_receipt();

-- Grants. Raw values (contacts.value) are readable by the gateway/effector side only.
REVOKE ALL ON SCHEMA mbos_comms FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA mbos_comms FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA mbos_comms FROM PUBLIC;
GRANT USAGE ON SCHEMA mbos_comms TO agent_read, agent_write, gateway, approver, policy_admin;
GRANT SELECT (contact_ref, subject_ref, channel, created_at) ON mbos_comms.contacts
    TO agent_read, agent_write, approver, policy_admin;
GRANT SELECT ON mbos_comms.contacts TO gateway;
GRANT SELECT ON mbos_comms.consent_events, mbos_comms.dnc_scrubs TO agent_read, agent_write, gateway, approver, policy_admin;
GRANT INSERT ON mbos_comms.contacts, mbos_comms.consent_events, mbos_comms.dnc_scrubs TO agent_write, gateway;
GRANT EXECUTE ON FUNCTION mbos_comms.enabling_event_guard(), mbos_comms.require_same_tx_receipt(),
    mbos_comms.reject_mutation(), mbos_comms.is_enabling(text, jsonb) TO agent_write, gateway;
