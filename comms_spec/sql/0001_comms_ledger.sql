-- F-07: consent ledger + DNC scrub store (lane F). PROPOSED for adoption by lane D (Agent 04 owns DDL, R1).
-- Idempotent. Every table is insert-only (no UPDATE/DELETE/TRUNCATE). State is derived from the
-- latest event. Raw contact values live ONLY in mbos_comms.contacts and are referenced everywhere
-- else by contact_ref, never copied (receipts carry contact_ref only).

CREATE SCHEMA IF NOT EXISTS mbos_comms;

CREATE OR REPLACE FUNCTION mbos_comms.reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'mbos_comms.% is insert-only (% rejected)', TG_TABLE_NAME, TG_OP;
END $$;

CREATE TABLE IF NOT EXISTS mbos_comms.contacts (
    contact_ref  text PRIMARY KEY CHECK (contact_ref ~ '^cref_[0-9A-HJKMNP-TV-Z]{26}$'),
    subject_ref  text NOT NULL,                       -- listing URL / party ref the planner uses as recipient.ref
    channel      text NOT NULL CHECK (channel IN ('sms', 'email', 'voice')),
    value        text NOT NULL,                       -- RAW contact value: stays here, never copied
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (channel, value)
);
CREATE INDEX IF NOT EXISTS contacts_subject_idx ON mbos_comms.contacts (subject_ref, channel);

CREATE TABLE IF NOT EXISTS mbos_comms.consent_events (
    seq          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    contact_ref  text NOT NULL REFERENCES mbos_comms.contacts (contact_ref),
    event        text NOT NULL CHECK (event IN ('granted', 'revoked')),
    basis        text NOT NULL,                       -- e.g. listing_published_contact, inbound_inquiry, written_opt_in, stop_keyword
    evidence_uri text,
    recorded_at  timestamptz NOT NULL,
    receipt_id   text NOT NULL UNIQUE                 -- the mbos.receipts row written in the same transaction
);
CREATE INDEX IF NOT EXISTS consent_events_contact_idx ON mbos_comms.consent_events (contact_ref, seq);

CREATE TABLE IF NOT EXISTS mbos_comms.dnc_scrubs (
    seq          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    contact_ref  text NOT NULL REFERENCES mbos_comms.contacts (contact_ref),
    scrubbed_at  timestamptz NOT NULL,
    listed       boolean NOT NULL,
    source       text NOT NULL,                       -- e.g. national_dnc_registry (fixture in dry-run)
    receipt_id   text NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS dnc_scrubs_contact_idx ON mbos_comms.dnc_scrubs (contact_ref, seq);

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['contacts', 'consent_events', 'dnc_scrubs'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = t || '_insert_only') THEN
            EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON mbos_comms.%I FOR EACH ROW '
                           'EXECUTE FUNCTION mbos_comms.reject_mutation()', t || '_insert_only', t);
            EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON mbos_comms.%I FOR EACH STATEMENT '
                           'EXECUTE FUNCTION mbos_comms.reject_mutation()', t || '_no_truncate', t);
        END IF;
    END LOOP;
END $$;
