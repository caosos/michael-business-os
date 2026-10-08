-- 0019_campaigns_human_capital.sql — READY_QUEUE D-23 (F-78 ruling; A-26 campaign contract, E-17 policy).
--
-- (a) set_mission / capital_fund / capital_withdraw enforce actor.type = human with a non-empty id INSIDE the function
--     for any session that is not an agent_write member, exactly like 0018 does for record_outcome. "An agent actor is
--     refused" now rests on the database, not on Operator-UI code. (agent_write sessions such as mbos_dbos keep the
--     0017 behaviour: the approver-membership check still applies to them.)
-- (b) mbos.campaigns: insert-only revisions keyed by (campaign_id, revision); body is a campaign.schema.json document,
--     checked structurally in SQL (full JSON-Schema validation is in the tests against the vendored schema).
--     set_campaign / cancel_campaign are approver-only, each writes a CONFIG_VERSION_BUMPED receipt (entity_type
--     campaign) in the same transaction. E-17 mirrored in a CHECK: only WATCH_ONLY/RECOMMEND may be ACTIVE.

CREATE FUNCTION mbos._require_human_owner(p_actor jsonb, p_what text) RETURNS void
LANGUAGE plpgsql STABLE AS $$
BEGIN
    IF NOT pg_has_role(session_user, 'agent_write', 'MEMBER')
       AND (p_actor->>'type' IS DISTINCT FROM 'human' OR coalesce(btrim(p_actor->>'id'), '') = '') THEN
        RAISE EXCEPTION 'mbos: role % may % only as a human (actor.type human with an id), got actor %',
            session_user, p_what, p_actor USING ERRCODE = '42501';
    END IF;
END $$;

-- set_mission: 0017 body plus the human guard (first statement, before any idempotent replay).
CREATE OR REPLACE FUNCTION mbos.set_mission(p_mission jsonb, p_actor jsonb, p_intent text, p_provenance_ids text[],
                                            p_idempotency_key text) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE prev mbos.receipts; m mbos.mission; id text;
BEGIN
    PERFORM mbos._require_human_owner(p_actor, 'set the mission');
    prev := mbos.idempotent_receipt(p_idempotency_key, 'CONFIG_VERSION_BUMPED');
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.entity_id; END IF;
    IF NOT (pg_has_role(current_user, 'approver', 'MEMBER') OR pg_has_role(current_user, 'mbos_owner', 'MEMBER')) THEN
        RAISE EXCEPTION 'mbos: only the owner channel (approver) may set the mission' USING ERRCODE = '42501';
    END IF;
    INSERT INTO mbos.mission (mission_version, period_start, period_end, weekly_target_usd, hours_available, notes,
                              created_by, provenance_ids)
    VALUES (coalesce(p_mission->>'mission_version', '1.0.0'), (p_mission->'period'->>'start')::date,
            (p_mission->'period'->>'end')::date, (p_mission->>'weekly_target_usd')::numeric,
            (p_mission->>'hours_available')::numeric, p_mission->>'notes', p_actor->>'id', p_provenance_ids)
    RETURNING * INTO m;
    PERFORM mbos.append_receipt(jsonb_build_object(
        'type', 'CONFIG_VERSION_BUMPED', 'actor', p_actor, 'intent', p_intent, 'entity_type', 'mission',
        'entity_id', m.mission_id, 'effect', 'create', 'idempotency_key', p_idempotency_key,
        'provenance_ids', to_jsonb(p_provenance_ids),
        'after_state', jsonb_build_object('weekly_target_usd', m.weekly_target_usd, 'hours_available', m.hours_available,
                                          'period_start', m.period_start, 'period_end', m.period_end),
        'details', jsonb_build_object('kind', 'generic')));
    RETURN m.mission_id;
END $$;

-- capital_fund / capital_withdraw both go through this one function.
CREATE OR REPLACE FUNCTION mbos._capital_owner_receipt(p_type text, p_amount numeric, p_actor jsonb, p_intent text,
                                                       p_provenance_ids text[], p_idempotency_key text) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE prev mbos.receipts; rc mbos.receipts;
BEGIN
    PERFORM mbos._require_human_owner(p_actor, 'move capital');
    prev := mbos.idempotent_receipt(p_idempotency_key, 'CONFIG_VERSION_BUMPED');
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.receipt_id; END IF;
    rc := mbos.append_receipt(jsonb_build_object(
        'type', 'CONFIG_VERSION_BUMPED', 'actor', p_actor, 'intent', p_intent, 'entity_type', p_type,
        'entity_id', 'capital:' || p_idempotency_key, 'effect', 'create', 'idempotency_key', p_idempotency_key,
        'provenance_ids', to_jsonb(p_provenance_ids),
        'after_state', jsonb_build_object('amount', p_amount, 'mode', 'dry_run', 'currency', 'USD'),
        'details', jsonb_build_object('kind', 'money', 'dry_run', true)));
    RETURN rc.receipt_id;
END $$;

-- ---------------------------------------------------------------------------
-- Campaigns (schema: campaign). One row per revision; the latest revision is current.
-- ---------------------------------------------------------------------------
CREATE TABLE mbos.campaigns (
    seq            bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    campaign_id    text NOT NULL CHECK (campaign_id ~ '^cmp_[0-9A-HJKMNP-TV-Z]{26}$'),
    revision       integer NOT NULL CHECK (revision >= 1),
    status         text NOT NULL CHECK (status IN ('ACTIVE','PAUSED','FULFILLED','EXPIRED','CANCELLED')),
    autonomy_level text NOT NULL CHECK (autonomy_level IN ('WATCH_ONLY','RECOMMEND','ASSISTED_DEAL','BOUNDED_AUTOPILOT')),
    body           jsonb NOT NULL CHECK (jsonb_typeof(body) = 'object'),
    created_at     timestamptz NOT NULL DEFAULT now(),
    created_by     text NOT NULL CHECK (btrim(created_by) <> ''),
    provenance_ids text[] NOT NULL CHECK (cardinality(provenance_ids) >= 1),
    PRIMARY KEY (campaign_id, revision),
    -- E-17 mirror: nothing above RECOMMEND may be stored as ACTIVE.
    CONSTRAINT campaign_active_only_up_to_recommend
        CHECK (status <> 'ACTIVE' OR autonomy_level IN ('WATCH_ONLY','RECOMMEND')),
    -- columns are projections of the body, never a second source of truth
    CONSTRAINT campaign_body_matches CHECK (
        body->>'campaign_version' = '1.0.0' AND body->>'campaign_id' = campaign_id
        AND body->>'status' = status AND body->'autonomy'->>'level' = autonomy_level
        AND body ?& ARRAY['owner','title','criteria','autonomy','stop_conditions']
        AND jsonb_typeof(body->'criteria') = 'object' AND body->'criteria' ?& ARRAY['category','max_price_usd']
        AND jsonb_typeof(body->'stop_conditions') = 'object'
        AND (autonomy_level <> 'BOUNDED_AUTOPILOT' OR body->'autonomy'->'limits' IS NOT NULL))
);
SELECT mbos.make_append_only('mbos.campaigns');

CREATE FUNCTION mbos.campaigns_require_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM mbos.require_receipt(ARRAY['CONFIG_VERSION_BUMPED'], 'entity_id', NEW.campaign_id,
                                 jsonb_build_object('revision', NEW.revision, 'status', NEW.status));
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER zz_campaigns_receipt AFTER INSERT ON mbos.campaigns
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION mbos.campaigns_require_receipt();

CREATE FUNCTION mbos._campaign_revise(p_body jsonb, p_actor jsonb, p_intent text, p_provenance_ids text[],
                                      p_idempotency_key text) RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE rev integer; cid text := p_body->>'campaign_id';
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('campaign:' || coalesce(cid, ''), 0));
    SELECT coalesce(max(revision), 0) + 1 INTO rev FROM mbos.campaigns WHERE campaign_id = cid;
    INSERT INTO mbos.campaigns (campaign_id, revision, status, autonomy_level, body, created_by, provenance_ids)
    VALUES (cid, rev, p_body->>'status', p_body->'autonomy'->>'level', p_body, p_actor->>'id', p_provenance_ids);
    PERFORM mbos.append_receipt(jsonb_build_object(
        'type', 'CONFIG_VERSION_BUMPED', 'actor', p_actor, 'intent', p_intent, 'entity_type', 'campaign',
        'entity_id', cid, 'effect', CASE WHEN rev = 1 THEN 'create' ELSE 'update' END,
        'idempotency_key', p_idempotency_key, 'provenance_ids', to_jsonb(p_provenance_ids),
        'after_state', jsonb_build_object('revision', rev, 'status', p_body->>'status',
                                          'autonomy_level', p_body->'autonomy'->>'level'),
        'details', jsonb_build_object('kind', 'generic')));
    RETURN rev;
END $$;

-- Michael sets (creates or revises) a campaign. Returns the campaign_id.
CREATE FUNCTION mbos.set_campaign(p_campaign jsonb, p_actor jsonb, p_intent text, p_provenance_ids text[],
                                  p_idempotency_key text) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE prev mbos.receipts;
BEGIN
    PERFORM mbos._require_human_owner(p_actor, 'set a campaign');
    prev := mbos.idempotent_receipt(p_idempotency_key, 'CONFIG_VERSION_BUMPED');
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.entity_id; END IF;
    IF NOT (pg_has_role(current_user, 'approver', 'MEMBER') OR pg_has_role(current_user, 'mbos_owner', 'MEMBER')) THEN
        RAISE EXCEPTION 'mbos: only the owner channel (approver) may set a campaign' USING ERRCODE = '42501';
    END IF;
    PERFORM mbos._campaign_revise(p_campaign, p_actor, p_intent, p_provenance_ids, p_idempotency_key);
    RETURN p_campaign->>'campaign_id';
END $$;

-- Cancel = a new CANCELLED revision of the current body (history kept). Refuses an unknown or already-cancelled campaign.
CREATE FUNCTION mbos.cancel_campaign(p_campaign_id text, p_actor jsonb, p_intent text, p_provenance_ids text[],
                                     p_idempotency_key text) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE prev mbos.receipts; cur mbos.campaigns;
BEGIN
    PERFORM mbos._require_human_owner(p_actor, 'cancel a campaign');
    prev := mbos.idempotent_receipt(p_idempotency_key, 'CONFIG_VERSION_BUMPED');
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.entity_id; END IF;
    IF NOT (pg_has_role(current_user, 'approver', 'MEMBER') OR pg_has_role(current_user, 'mbos_owner', 'MEMBER')) THEN
        RAISE EXCEPTION 'mbos: only the owner channel (approver) may cancel a campaign' USING ERRCODE = '42501';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('campaign:' || p_campaign_id, 0));
    SELECT * INTO cur FROM mbos.campaigns WHERE campaign_id = p_campaign_id ORDER BY revision DESC LIMIT 1;
    IF NOT FOUND THEN RAISE EXCEPTION 'mbos: no campaign %', p_campaign_id USING ERRCODE = 'P0002'; END IF;
    IF cur.status = 'CANCELLED' THEN
        RAISE EXCEPTION 'mbos: campaign % is already CANCELLED', p_campaign_id USING ERRCODE = '23514';
    END IF;
    PERFORM mbos._campaign_revise(cur.body || jsonb_build_object('status', 'CANCELLED'), p_actor, p_intent,
                                  p_provenance_ids, p_idempotency_key);
    RETURN p_campaign_id;
END $$;

-- Current revision of each campaign, in the contract's shape.
CREATE VIEW mbos.v_campaigns_current AS
    SELECT DISTINCT ON (c.campaign_id) c.campaign_id, c.revision, c.status, c.autonomy_level, c.body AS doc,
           c.created_at, c.created_by
    FROM mbos.campaigns c ORDER BY c.campaign_id, c.revision DESC;

REVOKE ALL ON mbos.campaigns, mbos.v_campaigns_current FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION mbos._require_human_owner(jsonb, text), mbos.campaigns_require_receipt(),
    mbos._campaign_revise(jsonb, jsonb, text, text[], text), mbos.set_campaign(jsonb, jsonb, text, text[], text),
    mbos.cancel_campaign(text, jsonb, text, text[], text) FROM PUBLIC;
GRANT SELECT ON mbos.campaigns, mbos.v_campaigns_current TO agent_read, agent_write, gateway, approver, policy_admin;
GRANT EXECUTE ON FUNCTION mbos._require_human_owner(jsonb, text) TO agent_write, approver;
GRANT EXECUTE ON FUNCTION mbos.campaigns_require_receipt() TO agent_write, gateway, approver, policy_admin, outbox_relay;
GRANT INSERT ON mbos.campaigns TO approver;
GRANT EXECUTE ON FUNCTION mbos._campaign_revise(jsonb, jsonb, text, text[], text),
    mbos.set_campaign(jsonb, jsonb, text, text[], text), mbos.cancel_campaign(text, jsonb, text, text[], text) TO approver;
