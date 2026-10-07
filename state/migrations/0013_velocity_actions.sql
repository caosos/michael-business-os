-- 0013_velocity_actions.sql — READY_QUEUE D-11 (requested by Agent 05 after E-02): caps.velocity_actions_per_hour.
-- Lane E's money bucket caps ACTIONS per hour (e.g. 3/h), not dollars. Counted under the same per-currency lock as
-- every other cap, so the rule lives in one place. Optional key: missing or null = no count cap (existing callers
-- unchanged); present = non-negative integer, else deny.

-- Reservations in the last hour over the bucket that have not been released (zero-amount rows included).
CREATE FUNCTION mbos.budget_velocity_actions_hour(p_categories text[], p_currency text, p_mode text,
                                                  p_at timestamptz DEFAULT now()) RETURNS bigint
LANGUAGE sql STABLE AS $$
    SELECT count(*) FROM mbos.budget_ledger r
    WHERE r.kind = 'reserve' AND (p_categories IS NULL OR r.category = ANY (p_categories))
      AND r.currency = p_currency AND r.mode = p_mode AND r.ts > p_at - interval '1 hour'
      AND NOT EXISTS (SELECT 1 FROM mbos.budget_ledger x WHERE x.reservation_id = r.entry_id AND x.kind = 'release')
$$;

CREATE OR REPLACE FUNCTION mbos.budget_reserve_caps(p_areq_id text, p_amount numeric, p_currency text, p_caps jsonb,
                                         p_mode text, p_actor jsonb, p_intent text, p_provenance_ids text[],
                                         p_idempotency_key text) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE
    a mbos.action_requests; prev mbos.receipts; e mbos.budget_ledger; k text; tz text; bucket text[];
    day_cat numeric; day_all numeric; hour_all numeric; hour_n bigint;
BEGIN
    prev := mbos.idempotent_receipt(p_idempotency_key, 'BUDGET_RESERVED');
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.entity_id; END IF;
    FOREACH k IN ARRAY ARRAY['per_action','daily','global_daily','velocity_per_hour'] LOOP
        -- a MISSING key denies; an explicit null is allowed only for velocity_per_hour (= no velocity cap)
        IF NOT (p_caps ? k) OR (jsonb_typeof(p_caps->k) IS DISTINCT FROM 'number'
                                AND NOT (k = 'velocity_per_hour' AND jsonb_typeof(p_caps->k) = 'null')) THEN
            RAISE EXCEPTION 'mbos: budget cap % missing or not a number — reservation denied (fail-closed)', k
                USING ERRCODE = 'MB006';
        END IF;
    END LOOP;
    tz := coalesce(p_caps->>'tz', 'America/Chicago');
    -- D-11: optional action-count velocity. Missing or null = no count cap; otherwise a non-negative integer.
    IF coalesce(jsonb_typeof(p_caps->'velocity_actions_per_hour'), 'null') <> 'null' THEN
        IF jsonb_typeof(p_caps->'velocity_actions_per_hour') <> 'number' THEN
            RAISE EXCEPTION 'mbos: velocity_actions_per_hour must be a non-negative integer or null — denied (fail-closed)'
                USING ERRCODE = 'MB006';
        END IF;
        IF (p_caps->>'velocity_actions_per_hour')::numeric < 0
           OR (p_caps->>'velocity_actions_per_hour')::numeric <> trunc((p_caps->>'velocity_actions_per_hour')::numeric) THEN
            RAISE EXCEPTION 'mbos: velocity_actions_per_hour must be a non-negative integer or null — denied (fail-closed)'
                USING ERRCODE = 'MB006';
        END IF;
    END IF;
    IF p_mode = 'live' AND p_amount > 0 THEN
        RAISE EXCEPTION 'mbos: live spend is capped at 0 in wave one' USING ERRCODE = 'MB006';
    END IF;
    SELECT * INTO a FROM mbos.action_requests WHERE action_request_id = p_areq_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'mbos: action request % not found', p_areq_id USING ERRCODE = 'MB404'; END IF;

    bucket := CASE WHEN jsonb_typeof(p_caps->'categories') = 'array'
                   THEN ARRAY(SELECT jsonb_array_elements_text(p_caps->'categories')) ELSE ARRAY[a.category] END;
    IF NOT a.category = ANY (bucket) THEN
        RAISE EXCEPTION 'mbos: category % is not in the cap bucket %', a.category, bucket USING ERRCODE = 'MB006';
    END IF;

    PERFORM mbos.budget_lock(p_currency);
    IF p_amount > (p_caps->>'per_action')::numeric THEN
        RAISE EXCEPTION 'mbos: % exceeds per_action cap %', p_amount, p_caps->>'per_action' USING ERRCODE = 'MB006';
    END IF;
    day_cat := mbos.budget_exposure_day(bucket, p_currency, p_mode, tz);
    IF day_cat + p_amount > (p_caps->>'daily')::numeric THEN
        RAISE EXCEPTION 'mbos: bucket % daily cap % exceeded (exposure %)', bucket, p_caps->>'daily', day_cat USING ERRCODE = 'MB006';
    END IF;
    day_all := mbos.budget_exposure_day(NULL, p_currency, p_mode, tz);
    IF day_all + p_amount > (p_caps->>'global_daily')::numeric THEN
        RAISE EXCEPTION 'mbos: global daily cap % exceeded (exposure %)', p_caps->>'global_daily', day_all USING ERRCODE = 'MB006';
    END IF;
    hour_all := mbos.budget_velocity_hour(bucket, p_currency, p_mode);
    IF jsonb_typeof(p_caps->'velocity_per_hour') = 'number'
       AND hour_all + p_amount > (p_caps->>'velocity_per_hour')::numeric THEN
        RAISE EXCEPTION 'mbos: velocity cap % per hour exceeded (last hour %)', p_caps->>'velocity_per_hour', hour_all
            USING ERRCODE = 'MB006';
    END IF;

    IF jsonb_typeof(p_caps->'velocity_actions_per_hour') = 'number' THEN
        hour_n := mbos.budget_velocity_actions_hour(bucket, p_currency, p_mode);
        IF hour_n + 1 > (p_caps->>'velocity_actions_per_hour')::numeric THEN
            RAISE EXCEPTION 'mbos: action velocity cap % per hour reached (last hour %)',
                p_caps->>'velocity_actions_per_hour', hour_n USING ERRCODE = 'MB006';
        END IF;
    END IF;

    INSERT INTO mbos.budget_ledger (kind, category, action_request_id, amount, currency, cap_applied, provenance_ids, mode)
    VALUES ('reserve', a.category, a.action_request_id, p_amount, p_currency, (p_caps->>'daily')::numeric,
            p_provenance_ids, p_mode)
    RETURNING * INTO e;
    PERFORM mbos.append_receipt(jsonb_build_object(
        'type', 'BUDGET_RESERVED', 'actor', p_actor, 'intent', p_intent, 'item_id', a.item_id,
        'action_request_id', a.action_request_id, 'capability', a.capability, 'payload_hash', a.payload_hash,
        'entity_type', 'budget_entry', 'entity_id', e.entry_id, 'effect', 'none', 'idempotency_key', p_idempotency_key,
        'provenance_ids', to_jsonb(p_provenance_ids),
        'budget_effect', jsonb_build_object('category', e.category, 'amount', e.amount, 'currency', e.currency),
        'after_state', jsonb_build_object('kind', 'reserve', 'mode', p_mode, 'caps', p_caps,
                                          'bucket', to_jsonb(bucket), 'exposure_day_bucket', day_cat + p_amount, 'exposure_day_all', day_all + p_amount,
                                          'last_hour', hour_all + p_amount, 'last_hour_actions', hour_n + 1),
        'details', jsonb_build_object('kind', 'money', 'dry_run', p_mode = 'dry_run')));
    RETURN e.entry_id;
END $$;

REVOKE EXECUTE ON FUNCTION mbos.budget_velocity_actions_hour(text[], text, text, timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION mbos.budget_velocity_actions_hour(text[], text, text, timestamptz)
    TO agent_read, agent_write, gateway, approver, policy_admin;
