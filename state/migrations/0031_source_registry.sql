-- 0031_source_registry.sql — READY_QUEUE D-37 / ADR-0015 P-74-3: location-scoped source registry and per-user listing interest. DRY-RUN.
--   * mbos.source_registry: one row per source (or per Craigslist subdomain). Every row carries a non-blank policy_ref.
--     Rows are loaded from config/sources.v1.json by mbos_state.sources.load_sources, which validates against config/sources.schema.json.
--     Readable by every role; written only by owner_channel via upsert_source (reviewed like policy). Rows are never deleted.
--   * mbos.user_item_interest: which user's own alert/feed surfaced which shared item. No table grants; read through
--     get_user_item_interest (caller's own user id, mbos._can_act_as) and written by record_user_item_interest (agent_write ingest).
CREATE TABLE mbos.source_registry (
    source_id        text PRIMARY KEY CHECK (source_id ~ '^[a-z][a-z0-9_]*$'),
    display_name     text NOT NULL CHECK (btrim(display_name) <> ''),
    scope            text NOT NULL CHECK (scope IN ('national', 'states', 'metro', 'point')),
    states           text[] CHECK (states IS NULL OR (cardinality(states) > 0 AND array_to_string(states, ',') ~ '^[A-Z]{2}(,[A-Z]{2})*$')),
    center_lat       double precision CHECK (center_lat BETWEEN -90 AND 90),
    center_lng       double precision CHECK (center_lng BETWEEN -180 AND 180),
    radius_mi        double precision CHECK (radius_mi > 0),
    subdomain        text CHECK (subdomain IS NULL OR btrim(subdomain) <> ''),
    access_mode      text NOT NULL CHECK (access_mode IN ('api', 'alert_email', 'manual', 'excluded')),
    status           text NOT NULL CHECK (status IN ('connected', 'fixture', 'not_connected', 'blocked')),
    policy_ref       text NOT NULL CHECK (btrim(policy_ref) <> ''),
    terms_checked_at date,
    note             text NOT NULL DEFAULT '',
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CHECK (scope NOT IN ('metro', 'point') OR (center_lat IS NOT NULL AND center_lng IS NOT NULL AND radius_mi IS NOT NULL)),
    CHECK (scope <> 'states' OR states IS NOT NULL)
);
GRANT SELECT ON mbos.source_registry TO agent_read, agent_write, gateway, approver, policy_admin, owner_channel;

CREATE FUNCTION mbos.upsert_source(p_row jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, mbos AS $$
DECLARE c jsonb := COALESCE(p_row -> 'coverage', '{}'::jsonb);
BEGIN
    IF NOT pg_has_role(session_user, 'owner_channel', 'MEMBER') THEN
        RAISE EXCEPTION 'mbos: role % may not change the source registry', session_user USING ERRCODE = '42501';
    END IF;
    INSERT INTO mbos.source_registry (source_id, display_name, scope, states, center_lat, center_lng, radius_mi, subdomain,
                                      access_mode, status, policy_ref, terms_checked_at, note)
    VALUES (p_row ->> 'source_id', p_row ->> 'display_name', c ->> 'scope',
            (SELECT array_agg(s) FROM jsonb_array_elements_text(c -> 'states') s),
            (c #>> '{center,lat}')::double precision, (c #>> '{center,lng}')::double precision,
            (c ->> 'radius_mi')::double precision, c ->> 'subdomain', p_row ->> 'access_mode', p_row ->> 'status',
            p_row ->> 'policy_ref', (p_row ->> 'terms_checked_at')::date, COALESCE(p_row ->> 'note', ''))
    ON CONFLICT (source_id) DO UPDATE SET display_name = EXCLUDED.display_name, scope = EXCLUDED.scope, states = EXCLUDED.states,
        center_lat = EXCLUDED.center_lat, center_lng = EXCLUDED.center_lng, radius_mi = EXCLUDED.radius_mi,
        subdomain = EXCLUDED.subdomain, access_mode = EXCLUDED.access_mode, status = EXCLUDED.status,
        policy_ref = EXCLUDED.policy_ref, terms_checked_at = EXCLUDED.terms_checked_at, note = EXCLUDED.note, updated_at = now();
END $$;
REVOKE EXECUTE ON FUNCTION mbos.upsert_source(jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION mbos.upsert_source(jsonb) TO owner_channel;

CREATE TABLE mbos.user_item_interest (
    user_id      text NOT NULL REFERENCES mbos.app_user (user_id),
    item_id      text NOT NULL REFERENCES mbos.items (item_id),
    source_id    text NOT NULL REFERENCES mbos.source_registry (source_id),
    received_at  timestamptz NOT NULL,
    PRIMARY KEY (user_id, item_id, source_id)
);

CREATE FUNCTION mbos.record_user_item_interest(p_user_id text, p_item_id text, p_source_id text, p_received_at timestamptz) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, mbos AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM mbos.app_user WHERE user_id = p_user_id AND status = 'active') THEN
        RAISE EXCEPTION 'mbos: unknown or inactive user %', p_user_id USING ERRCODE = '23503';
    END IF;
    INSERT INTO mbos.user_item_interest (user_id, item_id, source_id, received_at) VALUES (p_user_id, p_item_id, p_source_id, p_received_at)
    ON CONFLICT (user_id, item_id, source_id) DO UPDATE SET received_at = GREATEST(mbos.user_item_interest.received_at, EXCLUDED.received_at);
END $$;

CREATE FUNCTION mbos.get_user_item_interest(p_user_id text) RETURNS TABLE (item_id text, source_id text, received_at timestamptz)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, mbos AS $$
BEGIN
    IF NOT mbos._can_act_as(p_user_id) THEN
        RAISE EXCEPTION 'mbos: role % may not read interest for user %', session_user, p_user_id USING ERRCODE = '42501';
    END IF;
    RETURN QUERY SELECT i.item_id, i.source_id, i.received_at FROM mbos.user_item_interest i WHERE i.user_id = p_user_id ORDER BY i.received_at DESC, i.item_id;
END $$;
REVOKE EXECUTE ON FUNCTION mbos.record_user_item_interest(text, text, text, timestamptz), mbos.get_user_item_interest(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION mbos.record_user_item_interest(text, text, text, timestamptz) TO agent_write, owner_channel;
GRANT EXECUTE ON FUNCTION mbos.get_user_item_interest(text) TO agent_read, agent_write, owner_channel, approver;
