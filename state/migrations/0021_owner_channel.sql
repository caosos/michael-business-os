-- 0021_owner_channel.sql — READY_QUEUE D-25 (F-80 ruling: a human claim is not an identity; F-81, F-83).
--   A JSON actor claim is typed by the caller, so it cannot be what separates Michael from a workflow. The five owner
--   paths (set_mission, capital_fund, capital_withdraw, set_campaign, cancel_campaign) now require the DATABASE role
--   owner_channel, granted ONLY to the Operator UI login mbos_operator_ui (roles.sql). The human-actor check from
--   0019/0020 stays as a second layer. mbos_dbos (agent_write + approver + gateway) is refused even with a forged
--   {type:human,id:michael} and a real provenance id: EXECUTE and the INSERT privileges are moved from approver to
--   owner_channel, the role check runs first inside the functions, and the capital ledger trigger refuses a forged
--   capital_fund/capital_withdraw receipt appended straight through append_receipt by any other session.
--   record_outcome (0018) is unchanged.

CREATE OR REPLACE FUNCTION mbos._require_human_owner(p_actor jsonb, p_what text) RETURNS void
LANGUAGE plpgsql STABLE AS $$
BEGIN
    IF NOT pg_has_role(current_user, 'owner_channel', 'MEMBER') THEN
        RAISE EXCEPTION 'mbos: role % may not % (owner_channel only)', current_user, p_what USING ERRCODE = '42501';
    END IF;
    IF p_actor->>'type' IS DISTINCT FROM 'human' OR coalesce(btrim(p_actor->>'id'), '') = '' THEN
        RAISE EXCEPTION 'mbos: role % may % only as a human (actor.type human with an id), got actor %',
            session_user, p_what, p_actor USING ERRCODE = '42501';
    END IF;
END $$;

-- Capital ledger gate for fund/withdraw receipts (everything else in the function is 0017 verbatim).
CREATE OR REPLACE FUNCTION mbos.capital_entry_for(r mbos.receipts, p_active boolean, p_available numeric, p_earned numeric,
                                       p_item_deployed numeric, p_item_closed boolean,
                                       p_enforce_roles boolean DEFAULT true) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE
    amt numeric; net numeric; owner boolean := pg_has_role(session_user, 'mbos_owner', 'MEMBER');
    is_approver boolean := pg_has_role(session_user, 'approver', 'MEMBER');
    is_gateway boolean := pg_has_role(session_user, 'gateway', 'MEMBER'); real jsonb;
BEGIN
    -- fund / withdraw: owner channel only
    IF r.type = 'CONFIG_VERSION_BUMPED' AND r.entity_type IN ('capital_fund', 'capital_withdraw') THEN
        IF p_enforce_roles AND NOT pg_has_role(session_user, 'owner_channel', 'MEMBER') THEN
            RAISE EXCEPTION 'mbos: role % may not record capital funding (owner channel only)', session_user USING ERRCODE = '42501';
        END IF;
        amt := (r.after_state->>'amount')::numeric;
        IF amt IS NULL OR amt <= 0 THEN
            RAISE EXCEPTION 'mbos: capital % needs a positive amount', r.entity_type USING ERRCODE = 'MB006';
        END IF;
        IF r.entity_type = 'capital_fund' THEN
            RETURN jsonb_build_object('kind', 'fund', 'amount', amt);
        END IF;
        IF NOT p_active OR amt > greatest(p_earned, 0) OR amt > p_available THEN
            RAISE EXCEPTION 'mbos: withdrawal % exceeds earned working capital % / available %', amt, p_earned, p_available
                USING ERRCODE = 'MB006';
        END IF;
        RETURN jsonb_build_object('kind', 'withdraw', 'amount', amt);
    END IF;

    -- deploy: a committed purchase/money spend
    IF r.type = 'BUDGET_COMMITTED' AND r.item_id IS NOT NULL
       AND EXISTS (SELECT 1 FROM mbos.capital_deploy_categories c WHERE c.category = r.budget_effect->>'category') THEN
        IF NOT p_active THEN RETURN NULL; END IF;                                  -- ledger not funded yet: nothing accounted
        IF p_enforce_roles AND NOT (is_gateway OR is_approver OR owner) THEN
            RAISE EXCEPTION 'mbos: role % may not commit capital', session_user USING ERRCODE = '42501';
        END IF;
        IF r.budget_effect->>'currency' IS DISTINCT FROM 'USD' THEN
            RAISE EXCEPTION 'mbos: capital is USD only, got %', r.budget_effect->>'currency' USING ERRCODE = 'MB006';
        END IF;
        amt := (r.budget_effect->>'amount')::numeric;
        IF amt > p_available THEN
            RAISE EXCEPTION 'mbos: deploying % exceeds available_to_deploy % (capital protected; spend refused)', amt, p_available
                USING ERRCODE = 'MB006';
        END IF;
        RETURN jsonb_build_object('kind', 'deploy', 'amount', amt, 'item_id', r.item_id);
    END IF;

    -- close: the item's closing outcome, recorded by a HUMAN (agent-reported outcomes never move capital)
    IF r.type = 'OUTCOME_RECORDED' AND r.item_id IS NOT NULL
       AND EXISTS (SELECT 1 FROM mbos.capital_closing_kinds k WHERE k.kind = r.after_state->>'kind') THEN
        IF NOT p_active OR p_item_closed OR r.actor->>'type' <> 'human' THEN RETURN NULL; END IF;
        IF p_enforce_roles AND NOT (is_approver OR owner) THEN
            RAISE EXCEPTION 'mbos: role % may not close capital (owner channel only)', session_user USING ERRCODE = '42501';
        END IF;
        real := r.after_state->'realized';
        net := coalesce((real->>'net_profit')::numeric, (real->>'revenue')::numeric - (real->>'total_cost')::numeric);
        IF net IS NULL THEN RETURN NULL; END IF;                                   -- no numbers: stays open, listed as pending
        RETURN jsonb_build_object('kind', 'close', 'item_id', r.item_id, 'amount', p_item_deployed,
                                  'basis', p_item_deployed, 'net', net);
    END IF;
    RETURN NULL;
END $$;

-- F-81: campaign body checks beyond the structural CHECK. Strings are capped at 200 characters everywhere in the body.
CREATE FUNCTION mbos._campaign_validate(p_body jsonb) RETURNS void
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE c jsonb := p_body->'criteria'; k text; n numeric;
BEGIN
    IF jsonb_typeof(p_body) IS DISTINCT FROM 'object' THEN RAISE EXCEPTION 'mbos: campaign must be an object' USING ERRCODE = '23514'; END IF;
    FOREACH k IN ARRAY ARRAY['owner', 'title'] LOOP
        IF jsonb_typeof(p_body->k) IS DISTINCT FROM 'string' OR btrim(p_body->>k) = '' THEN
            RAISE EXCEPTION 'mbos: campaign.% must be a non-empty string', k USING ERRCODE = '23514';
        END IF;
    END LOOP;
    IF jsonb_typeof(c) IS DISTINCT FROM 'object' OR jsonb_typeof(c->'max_price_usd') IS DISTINCT FROM 'number' THEN
        RAISE EXCEPTION 'mbos: campaign.criteria.max_price_usd must be a number' USING ERRCODE = '23514';
    END IF;
    n := (c->>'max_price_usd')::numeric;
    IF n < 0 OR n >= 1e12 THEN
        RAISE EXCEPTION 'mbos: campaign.criteria.max_price_usd must be finite and >= 0, got %', n USING ERRCODE = '23514';
    END IF;
    IF jsonb_typeof(c->'category') IS DISTINCT FROM 'string' OR btrim(c->>'category') = '' THEN
        RAISE EXCEPTION 'mbos: campaign.criteria.category must be a non-empty string' USING ERRCODE = '23514';
    END IF;
    IF c ? 'keywords' AND (jsonb_typeof(c->'keywords') IS DISTINCT FROM 'array'
                           OR EXISTS (SELECT 1 FROM jsonb_array_elements(c->'keywords') e WHERE jsonb_typeof(e) <> 'string')) THEN
        RAISE EXCEPTION 'mbos: campaign.criteria.keywords must be an array of strings' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (SELECT 1 FROM jsonb_path_query(p_body, 'strict $.**') v
               WHERE jsonb_typeof(v) = 'string' AND length(v #>> '{}') > 200) THEN
        RAISE EXCEPTION 'mbos: campaign strings are limited to 200 characters' USING ERRCODE = '23514';
    END IF;
END $$;

-- set_campaign: 0019 body plus F-81 validation and F-83 (a CANCELLED campaign is terminal; cancel is not undone by a revise).
CREATE OR REPLACE FUNCTION mbos.set_campaign(p_campaign jsonb, p_actor jsonb, p_intent text, p_provenance_ids text[],
                                             p_idempotency_key text) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE prev mbos.receipts; cid text := p_campaign->>'campaign_id';
BEGIN
    PERFORM mbos._require_human_owner(p_actor, 'set a campaign');
    prev := mbos.idempotent_receipt(p_idempotency_key, 'CONFIG_VERSION_BUMPED');
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.entity_id; END IF;
    PERFORM mbos._campaign_validate(p_campaign);
    PERFORM pg_advisory_xact_lock(hashtextextended('campaign:' || coalesce(cid, ''), 0));
    IF (SELECT status FROM mbos.campaigns WHERE campaign_id = cid ORDER BY revision DESC LIMIT 1) = 'CANCELLED' THEN
        RAISE EXCEPTION 'mbos: campaign % is CANCELLED and cannot be revised or resurrected', cid USING ERRCODE = '23514';
    END IF;
    PERFORM mbos._campaign_revise(p_campaign, p_actor, p_intent, p_provenance_ids, p_idempotency_key);
    RETURN cid;
END $$;

-- Privileges: approver loses the five paths (and the INSERT rights behind them); owner_channel gets them.
REVOKE EXECUTE ON FUNCTION mbos.set_mission(jsonb, jsonb, text, text[], text),
    mbos._capital_owner_receipt(text, numeric, jsonb, text, text[], text),
    mbos.capital_fund(numeric, jsonb, text, text[], text), mbos.capital_withdraw(numeric, jsonb, text, text[], text),
    mbos._campaign_revise(jsonb, jsonb, text, text[], text), mbos.set_campaign(jsonb, jsonb, text, text[], text),
    mbos.cancel_campaign(text, jsonb, text, text[], text) FROM approver;
REVOKE INSERT ON mbos.mission, mbos.campaigns FROM approver;
REVOKE EXECUTE ON FUNCTION mbos._campaign_validate(jsonb) FROM PUBLIC;
GRANT USAGE ON SCHEMA mbos TO owner_channel;
GRANT EXECUTE ON FUNCTION mbos.set_mission(jsonb, jsonb, text, text[], text),
    mbos._capital_owner_receipt(text, numeric, jsonb, text, text[], text),
    mbos.capital_fund(numeric, jsonb, text, text[], text), mbos.capital_withdraw(numeric, jsonb, text, text[], text),
    mbos._campaign_revise(jsonb, jsonb, text, text[], text), mbos.set_campaign(jsonb, jsonb, text, text[], text),
    mbos.cancel_campaign(text, jsonb, text, text[], text), mbos._campaign_validate(jsonb) TO owner_channel;
GRANT INSERT ON mbos.mission, mbos.campaigns TO owner_channel;
