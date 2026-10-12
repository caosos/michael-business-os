-- 0030_user_state.sql — READY_QUEUE D-36 / ADR-0015 P-74-2: per-user prefs, saved/dismissed, and per-user watches. DRY-RUN.
--   * mbos.user_pref / mbos.user_item_state: no table grants. All reads and writes go through SECURITY DEFINER functions that
--     accept only the caller's own user id (mbos._can_act_as). Items stay shared public facts; one user's dismissal never hides
--     an item for another. Saved/dismissed live in user_item_state; user_pref keys are more, less, last, enabled.
--   * app_user.db_login: optional database login for a member. A session that is some user's db_login can act only as that user.
--     A session with no mapping (the UI service role, owner_channel/approver) acts on behalf of the user id it passes.
--   * auction_watches gains user_id (backfilled to the owner). One watch per (user, item); alerts are unique per watch and key,
--     so they fire once per user per item per threshold. Bid ceilings stay owner-only. The 7-arg watch_auction is unchanged
--     (it watches for the owner); the 8-arg overload takes the user id.
ALTER TABLE mbos.app_user ADD COLUMN db_login text UNIQUE CHECK (db_login IS NULL OR btrim(db_login) <> '');

CREATE FUNCTION mbos._can_act_as(p_user_id text) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, mbos AS $$
    SELECT EXISTS (SELECT 1 FROM mbos.app_user WHERE user_id = p_user_id AND status = 'active')
       AND CASE WHEN EXISTS (SELECT 1 FROM mbos.app_user WHERE db_login = session_user)
                THEN EXISTS (SELECT 1 FROM mbos.app_user WHERE db_login = session_user AND user_id = p_user_id)
                ELSE pg_has_role(session_user, 'owner_channel', 'MEMBER') OR pg_has_role(session_user, 'approver', 'MEMBER') END
$$;
REVOKE EXECUTE ON FUNCTION mbos._can_act_as(text) FROM PUBLIC;

CREATE TABLE mbos.user_pref (
    user_id     text NOT NULL REFERENCES mbos.app_user (user_id),
    key         text NOT NULL CHECK (key IN ('more', 'less', 'last', 'enabled')),
    value       jsonb NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, key)
);
CREATE TABLE mbos.user_item_state (
    user_id  text NOT NULL REFERENCES mbos.app_user (user_id),
    item_id  text NOT NULL REFERENCES mbos.items (item_id),
    state    text NOT NULL CHECK (state IN ('saved', 'dismissed')),
    at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, item_id)
);

CREATE FUNCTION mbos.set_user_pref(p_user_id text, p_key text, p_value jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, mbos AS $$
BEGIN
    IF NOT mbos._can_act_as(p_user_id) THEN
        RAISE EXCEPTION 'mbos: role % may not write prefs for user %', session_user, p_user_id USING ERRCODE = '42501';
    END IF;
    IF p_value IS NULL THEN DELETE FROM mbos.user_pref WHERE user_id = p_user_id AND key = p_key; RETURN; END IF;
    INSERT INTO mbos.user_pref (user_id, key, value) VALUES (p_user_id, p_key, p_value)
    ON CONFLICT (user_id, key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
END $$;

CREATE FUNCTION mbos.get_user_prefs(p_user_id text) RETURNS TABLE (key text, value jsonb)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, mbos AS $$
BEGIN
    IF NOT mbos._can_act_as(p_user_id) THEN
        RAISE EXCEPTION 'mbos: role % may not read prefs for user %', session_user, p_user_id USING ERRCODE = '42501';
    END IF;
    RETURN QUERY SELECT p.key, p.value FROM mbos.user_pref p WHERE p.user_id = p_user_id ORDER BY p.key;
END $$;

-- p_state NULL clears the user's mark on the item.
CREATE FUNCTION mbos.set_user_item_state(p_user_id text, p_item_id text, p_state text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, mbos AS $$
BEGIN
    IF NOT mbos._can_act_as(p_user_id) THEN
        RAISE EXCEPTION 'mbos: role % may not change item state for user %', session_user, p_user_id USING ERRCODE = '42501';
    END IF;
    IF p_state IS NULL THEN DELETE FROM mbos.user_item_state WHERE user_id = p_user_id AND item_id = p_item_id; RETURN; END IF;
    IF p_state NOT IN ('saved', 'dismissed') THEN RAISE EXCEPTION 'mbos: state must be saved or dismissed' USING ERRCODE = 'MB004'; END IF;
    IF NOT EXISTS (SELECT 1 FROM mbos.items WHERE item_id = p_item_id) THEN
        RAISE EXCEPTION 'mbos: item % not found', p_item_id USING ERRCODE = 'MB404';
    END IF;
    INSERT INTO mbos.user_item_state (user_id, item_id, state) VALUES (p_user_id, p_item_id, p_state)
    ON CONFLICT (user_id, item_id) DO UPDATE SET state = EXCLUDED.state, at = now();
END $$;

CREATE FUNCTION mbos.get_user_item_states(p_user_id text) RETURNS TABLE (item_id text, state text, at timestamptz)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, mbos AS $$
BEGIN
    IF NOT mbos._can_act_as(p_user_id) THEN
        RAISE EXCEPTION 'mbos: role % may not read item state for user %', session_user, p_user_id USING ERRCODE = '42501';
    END IF;
    RETURN QUERY SELECT s.item_id, s.state, s.at FROM mbos.user_item_state s WHERE s.user_id = p_user_id ORDER BY s.at, s.item_id;
END $$;

-- Per-user watchlist read (the shared view v_auction_watch_current stays for operators and agents).
CREATE FUNCTION mbos.get_user_watches(p_user_id text) RETURNS SETOF mbos.v_auction_watch_current
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, mbos AS $$
BEGIN
    IF NOT mbos._can_act_as(p_user_id) THEN
        RAISE EXCEPTION 'mbos: role % may not read watches for user %', session_user, p_user_id USING ERRCODE = '42501';
    END IF;
    RETURN QUERY SELECT v.* FROM mbos.v_auction_watch_current v WHERE v.user_id = p_user_id;
END $$;

DO $$ DECLARE oid_ text; BEGIN
    SELECT user_id INTO oid_ FROM mbos.app_user WHERE role = 'owner';
    EXECUTE format('ALTER TABLE mbos.auction_watches ADD COLUMN user_id text NOT NULL DEFAULT %L', oid_);   -- backfills existing rows to the owner
END $$;
ALTER TABLE mbos.auction_watches ALTER COLUMN user_id DROP DEFAULT;
ALTER TABLE mbos.auction_watches ADD CONSTRAINT auction_watches_user_fk FOREIGN KEY (user_id) REFERENCES mbos.app_user (user_id);
ALTER TABLE mbos.auction_watches DROP CONSTRAINT auction_watches_item_id_key;
ALTER TABLE mbos.auction_watches ADD CONSTRAINT auction_watches_user_item_key UNIQUE (user_id, item_id);

CREATE OR REPLACE VIEW mbos.v_auction_watch_current AS
SELECT w.watch_id, w.item_id, w.price_alert_usd, w.closing_alert_hours,
       coalesce((SELECT e.closes_at FROM mbos.auction_watch_events e WHERE e.watch_id = w.watch_id AND e.kind = 'observation'
                  AND e.closes_at IS NOT NULL ORDER BY e.event_id DESC LIMIT 1), w.closes_at) AS closes_at,
       o.current_bid, o.bid_count, o.observed_at,
       (SELECT e.ceiling_usd FROM mbos.auction_watch_events e WHERE e.watch_id = w.watch_id AND e.kind = 'ceiling'
         ORDER BY e.event_id DESC LIMIT 1) AS bid_ceiling_usd,
       EXISTS (SELECT 1 FROM mbos.auction_watch_events e WHERE e.watch_id = w.watch_id AND e.kind = 'stopped') AS stopped,
       coalesce((SELECT array_agg(e.alert_kind ORDER BY e.event_id) FROM mbos.auction_watch_events e
                  WHERE e.watch_id = w.watch_id AND e.kind = 'alert'), '{}') AS alerts_fired,
       w.user_id
  FROM mbos.auction_watches w
  LEFT JOIN LATERAL (SELECT e.current_bid, e.bid_count, e.observed_at FROM mbos.auction_watch_events e
                      WHERE e.watch_id = w.watch_id AND e.kind = 'observation' ORDER BY e.event_id DESC LIMIT 1) o ON true;

CREATE FUNCTION mbos.watch_auction(p_item_id text, p_closes_at timestamptz, p_price_alert_usd numeric, p_closing_alert_hours numeric,
                                   p_user_id text, p_actor jsonb, p_provenance_ids text[], p_idempotency_key text) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, mbos AS $$
DECLARE who text; prev mbos.receipts; wid text := mbos.new_id('watch');
BEGIN
    who := mbos._watch_require_human(p_actor, p_provenance_ids, 'watch an auction');
    IF NOT EXISTS (SELECT 1 FROM mbos.app_user WHERE user_id = p_user_id AND status = 'active') THEN
        RAISE EXCEPTION 'mbos: user % not found or disabled', p_user_id USING ERRCODE = 'MB404';
    END IF;
    prev := mbos.idempotent_receipt(p_idempotency_key, 'ITEM_STATE_CHANGED');
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.entity_id; END IF;
    IF NOT EXISTS (SELECT 1 FROM mbos.items WHERE item_id = p_item_id) THEN
        RAISE EXCEPTION 'mbos: item % not found', p_item_id USING ERRCODE = 'MB404';
    END IF;
    IF EXISTS (SELECT 1 FROM mbos.auction_watches WHERE item_id = p_item_id AND user_id = p_user_id) THEN
        RAISE EXCEPTION 'mbos: item % is already on the watchlist', p_item_id USING ERRCODE = 'MB006';
    END IF;
    INSERT INTO mbos.auction_watches (watch_id, item_id, user_id, created_by, closes_at, price_alert_usd, closing_alert_hours, provenance_id)
    VALUES (wid, p_item_id, p_user_id, who, p_closes_at, p_price_alert_usd, coalesce(p_closing_alert_hours, 6), p_provenance_ids[1]);
    PERFORM mbos.append_receipt(jsonb_build_object(
        'type', 'ITEM_STATE_CHANGED', 'actor', p_actor, 'intent', who || ' put the auction on the watchlist (dry-run, no bidding)',
        'item_id', p_item_id, 'entity_type', 'auction_watch', 'entity_id', wid, 'effect', 'create', 'idempotency_key', p_idempotency_key,
        'provenance_ids', to_jsonb(p_provenance_ids),
        'after_state', jsonb_build_object('user_id', p_user_id, 'closes_at', p_closes_at, 'price_alert_usd', p_price_alert_usd,
                                          'closing_alert_hours', coalesce(p_closing_alert_hours, 6), 'mode', 'dry_run')));
    RETURN wid;
END $$;
REVOKE EXECUTE ON FUNCTION mbos.watch_auction(text, timestamptz, numeric, numeric, text, jsonb, text[], text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION mbos.watch_auction(text, timestamptz, numeric, numeric, text, jsonb, text[], text) TO owner_channel;

CREATE OR REPLACE FUNCTION mbos.watch_auction(p_item_id text, p_closes_at timestamptz, p_price_alert_usd numeric, p_closing_alert_hours numeric,
                                              p_actor jsonb, p_provenance_ids text[], p_idempotency_key text) RETURNS text
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, mbos AS $$
    SELECT mbos.watch_auction(p_item_id, p_closes_at, p_price_alert_usd, p_closing_alert_hours,
                              (SELECT user_id FROM mbos.app_user WHERE role = 'owner'), p_actor, p_provenance_ids, p_idempotency_key)
$$;

REVOKE EXECUTE ON FUNCTION mbos.set_user_pref(text, text, jsonb), mbos.get_user_prefs(text), mbos.set_user_item_state(text, text, text),
    mbos.get_user_item_states(text), mbos.get_user_watches(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION mbos.set_user_pref(text, text, jsonb), mbos.get_user_prefs(text), mbos.set_user_item_state(text, text, text),
    mbos.get_user_item_states(text), mbos.get_user_watches(text) TO agent_read, agent_write, owner_channel, approver;
