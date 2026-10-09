-- 0028_auction_watch.sql — READY_QUEUE D-33: auction watchlist, price/closing alerts, approved bid ceiling. DRY-RUN STORAGE ONLY.
--   * There is NO bid path: nothing here (or anywhere in the spine) submits, places or schedules a bid, creates an action
--     request, or touches the capital ledger. An "approved bid ceiling" is a number Michael recorded; it authorizes nothing
--     until bid integration and authorization are verified (a later, separately gated task).
--   * mbos.watch_auction(item, closes_at, price_alert_usd, closing_alert_hours, ...): owner_channel + human actor.
--   * mbos.record_watch_observation(watch, current_bid, bid_count, observed_at, closes_at?, ...): owner_channel or agent_write.
--     Appends the observation and, in the same transaction, fires each alert at most once per watch (UNIQUE watch_id,dedupe_key):
--     'price' (bid >= price_alert_usd), 'closing' (within closing_alert_hours of close, before close), 'ceiling_reached'
--     (bid >= approved ceiling). Returns the alert kinds fired by THIS call (an alert is a stored record; nothing is sent).
--   * mbos.set_bid_ceiling / mbos.stop_watch: owner_channel + human actor + human provenance. Latest ceiling wins.
--   * Every write has a receipt (ITEM_STATE_CHANGED, entity_type auction_watch). Tables are append-only.

CREATE TABLE mbos.auction_watches (
    watch_id             text PRIMARY KEY CHECK (watch_id ~ '^watch_[0-9A-HJKMNP-TV-Z]{26}$'),
    item_id              text NOT NULL UNIQUE REFERENCES mbos.items (item_id),
    created_at           timestamptz NOT NULL DEFAULT now(),
    created_by           text NOT NULL CHECK (btrim(created_by) <> ''),
    closes_at            timestamptz NOT NULL,
    price_alert_usd      numeric(12,2) CHECK (price_alert_usd IS NULL OR price_alert_usd > 0),
    closing_alert_hours  numeric(6,2) NOT NULL DEFAULT 6 CHECK (closing_alert_hours > 0 AND closing_alert_hours <= 168),
    provenance_id        text NOT NULL REFERENCES mbos.provenance (provenance_id)
);
SELECT mbos.make_append_only('mbos.auction_watches');

CREATE TABLE mbos.auction_watch_events (
    event_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    watch_id      text NOT NULL REFERENCES mbos.auction_watches (watch_id),
    ts            timestamptz NOT NULL DEFAULT now(),
    kind          text NOT NULL CHECK (kind IN ('observation', 'alert', 'ceiling', 'stopped')),
    observed_at   timestamptz,
    current_bid   numeric(12,2) CHECK (current_bid IS NULL OR current_bid >= 0),
    bid_count     integer CHECK (bid_count IS NULL OR bid_count >= 0),
    closes_at     timestamptz,
    alert_kind    text CHECK (alert_kind IN ('price', 'closing', 'ceiling_reached')),
    dedupe_key    text,
    ceiling_usd   numeric(12,2) CHECK (ceiling_usd IS NULL OR ceiling_usd > 0),
    actor         jsonb NOT NULL,
    note          text,
    CONSTRAINT awe_shape CHECK (
        (kind = 'observation' AND observed_at IS NOT NULL AND current_bid IS NOT NULL AND bid_count IS NOT NULL AND dedupe_key IS NULL)
     OR (kind = 'alert' AND alert_kind IS NOT NULL AND dedupe_key = alert_kind)
     OR (kind = 'ceiling' AND ceiling_usd IS NOT NULL)
     OR (kind = 'stopped')),
    CONSTRAINT awe_alert_once UNIQUE (watch_id, dedupe_key)       -- NULLs never collide: only alerts carry a key
);
CREATE INDEX awe_watch_idx ON mbos.auction_watch_events (watch_id, event_id);
SELECT mbos.make_append_only('mbos.auction_watch_events');

-- Latest observation, effective close, current ceiling, stopped flag and fired alerts per watch.
CREATE VIEW mbos.v_auction_watch_current AS
SELECT w.watch_id, w.item_id, w.price_alert_usd, w.closing_alert_hours,
       coalesce((SELECT e.closes_at FROM mbos.auction_watch_events e WHERE e.watch_id = w.watch_id AND e.kind = 'observation'
                  AND e.closes_at IS NOT NULL ORDER BY e.event_id DESC LIMIT 1), w.closes_at) AS closes_at,
       o.current_bid, o.bid_count, o.observed_at,
       (SELECT e.ceiling_usd FROM mbos.auction_watch_events e WHERE e.watch_id = w.watch_id AND e.kind = 'ceiling'
         ORDER BY e.event_id DESC LIMIT 1) AS bid_ceiling_usd,
       EXISTS (SELECT 1 FROM mbos.auction_watch_events e WHERE e.watch_id = w.watch_id AND e.kind = 'stopped') AS stopped,
       coalesce((SELECT array_agg(e.alert_kind ORDER BY e.event_id) FROM mbos.auction_watch_events e
                  WHERE e.watch_id = w.watch_id AND e.kind = 'alert'), '{}') AS alerts_fired
  FROM mbos.auction_watches w
  LEFT JOIN LATERAL (SELECT e.current_bid, e.bid_count, e.observed_at FROM mbos.auction_watch_events e
                      WHERE e.watch_id = w.watch_id AND e.kind = 'observation' ORDER BY e.event_id DESC LIMIT 1) o ON true;

GRANT SELECT ON mbos.auction_watches, mbos.auction_watch_events, mbos.v_auction_watch_current
    TO agent_read, agent_write, gateway, approver, policy_admin;

-- Shared guard: owner channel session, human actor with an id, provenance_ids[1] a human provenance naming that human.
CREATE FUNCTION mbos._watch_require_human(p_actor jsonb, p_provenance_ids text[], p_what text) RETURNS text
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, mbos AS $$
DECLARE who text; pid text := p_provenance_ids[1];
BEGIN
    IF NOT pg_has_role(session_user, 'owner_channel', 'MEMBER') THEN
        RAISE EXCEPTION 'mbos: role % may not % (owner_channel only)', session_user, p_what USING ERRCODE = '42501';
    END IF;
    IF p_actor->>'type' IS DISTINCT FROM 'human' OR coalesce(btrim(p_actor->>'id'), '') = '' THEN
        RAISE EXCEPTION 'mbos: % only by a human (actor.type human with an id), got actor %', p_what, p_actor USING ERRCODE = '42501';
    END IF;
    who := btrim(p_actor->>'id');
    IF pid IS NULL OR NOT EXISTS (SELECT 1 FROM mbos.provenance WHERE provenance_id = pid AND actor_type = 'human' AND human_actor = who) THEN
        RAISE EXCEPTION 'mbos: provenance_ids[1] must be a human provenance record naming %', who USING ERRCODE = 'MB004';
    END IF;
    RETURN who;
END $$;
REVOKE EXECUTE ON FUNCTION mbos._watch_require_human(jsonb, text[], text) FROM PUBLIC;

CREATE FUNCTION mbos.watch_auction(p_item_id text, p_closes_at timestamptz, p_price_alert_usd numeric, p_closing_alert_hours numeric,
                                   p_actor jsonb, p_provenance_ids text[], p_idempotency_key text) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, mbos AS $$
DECLARE who text; prev mbos.receipts; wid text := mbos.new_id('watch');
BEGIN
    who := mbos._watch_require_human(p_actor, p_provenance_ids, 'watch an auction');
    prev := mbos.idempotent_receipt(p_idempotency_key, 'ITEM_STATE_CHANGED');
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.entity_id; END IF;
    IF NOT EXISTS (SELECT 1 FROM mbos.items WHERE item_id = p_item_id) THEN
        RAISE EXCEPTION 'mbos: item % not found', p_item_id USING ERRCODE = 'MB404';
    END IF;
    IF EXISTS (SELECT 1 FROM mbos.auction_watches WHERE item_id = p_item_id) THEN
        RAISE EXCEPTION 'mbos: item % is already on the watchlist', p_item_id USING ERRCODE = 'MB006';
    END IF;
    INSERT INTO mbos.auction_watches (watch_id, item_id, created_by, closes_at, price_alert_usd, closing_alert_hours, provenance_id)
    VALUES (wid, p_item_id, who, p_closes_at, p_price_alert_usd, coalesce(p_closing_alert_hours, 6), p_provenance_ids[1]);
    PERFORM mbos.append_receipt(jsonb_build_object(
        'type', 'ITEM_STATE_CHANGED', 'actor', p_actor, 'intent', who || ' put the auction on the watchlist (dry-run, no bidding)',
        'item_id', p_item_id, 'entity_type', 'auction_watch', 'entity_id', wid, 'effect', 'create', 'idempotency_key', p_idempotency_key,
        'provenance_ids', to_jsonb(p_provenance_ids),
        'after_state', jsonb_build_object('closes_at', p_closes_at, 'price_alert_usd', p_price_alert_usd,
                                          'closing_alert_hours', coalesce(p_closing_alert_hours, 6), 'mode', 'dry_run')));
    RETURN wid;
END $$;
REVOKE EXECUTE ON FUNCTION mbos.watch_auction(text, timestamptz, numeric, numeric, jsonb, text[], text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION mbos.watch_auction(text, timestamptz, numeric, numeric, jsonb, text[], text) TO owner_channel;

CREATE FUNCTION mbos.set_bid_ceiling(p_watch_id text, p_ceiling_usd numeric, p_note text, p_actor jsonb,
                                     p_provenance_ids text[], p_idempotency_key text) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, mbos AS $$
DECLARE who text; prev mbos.receipts; w mbos.auction_watches; note text := btrim(coalesce(p_note, ''));
BEGIN
    who := mbos._watch_require_human(p_actor, p_provenance_ids, 'approve a bid ceiling');
    IF p_ceiling_usd IS NULL OR p_ceiling_usd < 0.01 OR p_ceiling_usd > 10000000 OR p_ceiling_usd <> round(p_ceiling_usd, 2) THEN
        RAISE EXCEPTION 'mbos: bid ceiling must be 0.01..10,000,000 USD with at most 2 decimals, got %', p_ceiling_usd USING ERRCODE = 'MB004';
    END IF;
    IF length(note) > 2000 THEN RAISE EXCEPTION 'mbos: note too long' USING ERRCODE = 'MB004'; END IF;
    prev := mbos.idempotent_receipt(p_idempotency_key, 'ITEM_STATE_CHANGED');
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.receipt_id; END IF;
    SELECT * INTO w FROM mbos.auction_watches WHERE watch_id = p_watch_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'mbos: watch % not found', p_watch_id USING ERRCODE = 'MB404'; END IF;
    IF EXISTS (SELECT 1 FROM mbos.auction_watch_events WHERE watch_id = p_watch_id AND kind = 'stopped') THEN
        RAISE EXCEPTION 'mbos: watch % is stopped', p_watch_id USING ERRCODE = 'MB006';
    END IF;
    INSERT INTO mbos.auction_watch_events (watch_id, kind, ceiling_usd, actor, note) VALUES (p_watch_id, 'ceiling', p_ceiling_usd, p_actor, nullif(note, ''));
    RETURN (mbos.append_receipt(jsonb_build_object(
        'type', 'ITEM_STATE_CHANGED', 'actor', p_actor, 'intent', who || ' recorded an approved bid ceiling (storage only; authorizes no bid)',
        'item_id', w.item_id, 'entity_type', 'auction_watch', 'entity_id', p_watch_id, 'effect', 'update', 'idempotency_key', p_idempotency_key,
        'provenance_ids', to_jsonb(p_provenance_ids),
        'after_state', jsonb_build_object('bid_ceiling_usd', p_ceiling_usd, 'mode', 'dry_run')))).receipt_id;
END $$;
REVOKE EXECUTE ON FUNCTION mbos.set_bid_ceiling(text, numeric, text, jsonb, text[], text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION mbos.set_bid_ceiling(text, numeric, text, jsonb, text[], text) TO owner_channel;

CREATE FUNCTION mbos.stop_watch(p_watch_id text, p_note text, p_actor jsonb, p_provenance_ids text[], p_idempotency_key text) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, mbos AS $$
DECLARE who text; prev mbos.receipts; w mbos.auction_watches;
BEGIN
    who := mbos._watch_require_human(p_actor, p_provenance_ids, 'stop a watch');
    prev := mbos.idempotent_receipt(p_idempotency_key, 'ITEM_STATE_CHANGED');
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.receipt_id; END IF;
    SELECT * INTO w FROM mbos.auction_watches WHERE watch_id = p_watch_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'mbos: watch % not found', p_watch_id USING ERRCODE = 'MB404'; END IF;
    IF EXISTS (SELECT 1 FROM mbos.auction_watch_events WHERE watch_id = p_watch_id AND kind = 'stopped') THEN
        RAISE EXCEPTION 'mbos: watch % is already stopped', p_watch_id USING ERRCODE = 'MB006';
    END IF;
    INSERT INTO mbos.auction_watch_events (watch_id, kind, actor, note) VALUES (p_watch_id, 'stopped', p_actor, left(btrim(coalesce(p_note, '')), 2000));
    RETURN (mbos.append_receipt(jsonb_build_object(
        'type', 'ITEM_STATE_CHANGED', 'actor', p_actor, 'intent', who || ' stopped the watch', 'item_id', w.item_id,
        'entity_type', 'auction_watch', 'entity_id', p_watch_id, 'effect', 'update', 'idempotency_key', p_idempotency_key,
        'provenance_ids', to_jsonb(p_provenance_ids), 'after_state', jsonb_build_object('stopped', true)))).receipt_id;
END $$;
REVOKE EXECUTE ON FUNCTION mbos.stop_watch(text, text, jsonb, text[], text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION mbos.stop_watch(text, text, jsonb, text[], text) TO owner_channel;

-- Returns the alert kinds fired by this call (empty array if none, or on an idempotent replay).
CREATE FUNCTION mbos.record_watch_observation(p_watch_id text, p_current_bid numeric, p_bid_count integer, p_observed_at timestamptz,
                                              p_closes_at timestamptz, p_actor jsonb, p_provenance_ids text[], p_idempotency_key text)
RETURNS text[] LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, mbos AS $$
DECLARE prev mbos.receipts; v mbos.v_auction_watch_current; w mbos.auction_watches; fired text[] := '{}'; k text; hit boolean;
        eff_close timestamptz;
BEGIN
    IF NOT (pg_has_role(session_user, 'owner_channel', 'MEMBER') OR pg_has_role(session_user, 'agent_write', 'MEMBER')) THEN
        RAISE EXCEPTION 'mbos: role % may not record a watch observation', session_user USING ERRCODE = '42501';
    END IF;
    IF p_provenance_ids IS NULL OR cardinality(p_provenance_ids) < 1
       OR NOT EXISTS (SELECT 1 FROM mbos.provenance WHERE provenance_id = p_provenance_ids[1]) THEN
        RAISE EXCEPTION 'mbos: an observation needs provenance_ids[1] (source and freshness)' USING ERRCODE = 'MB004';
    END IF;
    prev := mbos.idempotent_receipt(p_idempotency_key, 'ITEM_STATE_CHANGED');
    IF prev.receipt_id IS NOT NULL THEN RETURN '{}'; END IF;
    SELECT * INTO w FROM mbos.auction_watches WHERE watch_id = p_watch_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'mbos: watch % not found', p_watch_id USING ERRCODE = 'MB404'; END IF;
    IF EXISTS (SELECT 1 FROM mbos.auction_watch_events WHERE watch_id = p_watch_id AND kind = 'stopped') THEN
        RAISE EXCEPTION 'mbos: watch % is stopped', p_watch_id USING ERRCODE = 'MB006';
    END IF;
    INSERT INTO mbos.auction_watch_events (watch_id, kind, observed_at, current_bid, bid_count, closes_at, actor)
    VALUES (p_watch_id, 'observation', p_observed_at, p_current_bid, p_bid_count, p_closes_at, p_actor);
    SELECT * INTO v FROM mbos.v_auction_watch_current WHERE watch_id = p_watch_id;
    eff_close := v.closes_at;
    FOREACH k IN ARRAY ARRAY['price', 'closing', 'ceiling_reached'] LOOP
        hit := CASE k
            WHEN 'price' THEN v.price_alert_usd IS NOT NULL AND p_current_bid >= v.price_alert_usd
            WHEN 'closing' THEN p_observed_at < eff_close AND p_observed_at >= eff_close - make_interval(secs => v.closing_alert_hours * 3600)
            ELSE v.bid_ceiling_usd IS NOT NULL AND p_current_bid >= v.bid_ceiling_usd END;
        IF hit THEN
            INSERT INTO mbos.auction_watch_events (watch_id, kind, alert_kind, dedupe_key, observed_at, current_bid, bid_count, actor)
            VALUES (p_watch_id, 'alert', k, k, p_observed_at, p_current_bid, p_bid_count, p_actor)
            ON CONFLICT ON CONSTRAINT awe_alert_once DO NOTHING;
            IF FOUND THEN fired := fired || k; END IF;
        END IF;
    END LOOP;
    PERFORM mbos.append_receipt(jsonb_build_object(
        'type', 'ITEM_STATE_CHANGED', 'actor', p_actor, 'intent', 'recorded an auction observation (dry-run; alerts are records, nothing is sent or bid)',
        'item_id', w.item_id, 'entity_type', 'auction_watch', 'entity_id', p_watch_id, 'effect', 'update', 'idempotency_key', p_idempotency_key,
        'provenance_ids', to_jsonb(p_provenance_ids),
        'after_state', jsonb_build_object('current_bid', p_current_bid, 'bid_count', p_bid_count, 'observed_at', p_observed_at,
                                          'alerts_fired', to_jsonb(fired), 'mode', 'dry_run')));
    RETURN fired;
END $$;
REVOKE EXECUTE ON FUNCTION mbos.record_watch_observation(text, numeric, integer, timestamptz, timestamptz, jsonb, text[], text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION mbos.record_watch_observation(text, numeric, integer, timestamptz, timestamptz, jsonb, text[], text)
    TO owner_channel, agent_write;
