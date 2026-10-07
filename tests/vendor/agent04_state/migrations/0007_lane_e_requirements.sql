-- 0007_lane_e_requirements.sql — READY_QUEUE D-04: fold Lane E's requirements into the state spine
-- (origin/research/agent-05-governance:docs/integration/05-requirements-for-04-migration-0005.md, ruling R5).
--   §1 PANIC: panic_set() / panic_events / panic_current; engage = gateway|approver|policy_admin,
--      release = approver only; L3 engage cancels approved/auto_approved requests in the same transaction;
--      bootstrap FROZEN.
--   §2 effector_calls = execution claim: executing -> executed|failed exactly once; never deleted.
--   §3 gateway edges: approved->expired, approved->failed, executing->cancelled_by_freeze.
--   §4 budget: mode dry_run|live (live forced to 0), amount >= 0, multi-cap reserve under one lock,
--      policy-day exposure in a timezone.
--   §7 grants.

-- ---------------------------------------------------------------------------
-- §3 action-request edges (+ who may cancel on freeze: whoever may engage L3)
-- ---------------------------------------------------------------------------
INSERT INTO mbos.action_request_transitions VALUES
    ('approved','expired',               '{gateway}'),   -- G2: expired after YES, before execution
    ('approved','failed',                '{gateway}'),   -- G3: payload hash mismatch at execution (terminal)
    ('executing','cancelled_by_freeze',  '{gateway}');   -- PANIC re-read before the effector call
UPDATE mbos.action_request_transitions SET allowed_roles = '{gateway,approver,policy_admin}'
WHERE to_status = 'cancelled_by_freeze' AND from_status IN ('approved','auto_approved');

-- ---------------------------------------------------------------------------
-- §1 PANIC. Storage stays the sealed, append-only panic_state (05 PanicStore body, cjson_sha256 checksum);
-- each revision now also records the event that produced it.
-- ---------------------------------------------------------------------------
ALTER TABLE mbos.panic_state
    ADD COLUMN level  text CHECK (level IN ('L1','L2','L3')),
    ADD COLUMN target text,
    ADD COLUMN engage boolean,
    ADD COLUMN actor  jsonb,
    ADD COLUMN reason text CHECK (reason IS NULL OR length(btrim(reason)) > 0),
    ADD CONSTRAINT panic_target_per_level CHECK (level IS NULL OR ((level = 'L3') = (target IS NULL)));

CREATE FUNCTION mbos.panic_set(p_level text, p_target text, p_engage boolean, p_actor jsonb, p_reason text,
                               p_provenance_ids text[], p_idempotency_key text) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE
    prev mbos.receipts; s record; before jsonb; after jsonb; stamp jsonb; key text; next_rev int;
    sealed jsonb; rc mbos.receipts; a mbos.action_requests; owner boolean;
BEGIN
    prev := mbos.idempotent_receipt(p_idempotency_key, 'KILL_SWITCH_CHANGED');
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.receipt_id; END IF;
    owner := pg_has_role(current_user, 'mbos_owner', 'MEMBER');
    IF p_engage AND NOT (owner OR pg_has_role(current_user, 'gateway', 'MEMBER')
                         OR pg_has_role(current_user, 'approver', 'MEMBER')
                         OR pg_has_role(current_user, 'policy_admin', 'MEMBER')) THEN
        RAISE EXCEPTION 'mbos: role % may not engage PANIC', current_user USING ERRCODE = '42501';
    END IF;
    IF NOT p_engage AND NOT (owner OR pg_has_role(current_user, 'approver', 'MEMBER')) THEN
        RAISE EXCEPTION 'mbos: releasing PANIC requires approver (Michael)' USING ERRCODE = '42501';
    END IF;
    IF p_level NOT IN ('L1','L2','L3') THEN
        RAISE EXCEPTION 'mbos: unknown PANIC level %', p_level USING ERRCODE = 'MB004';
    END IF;
    IF (p_level = 'L3') <> (p_target IS NULL) OR (p_target IS NOT NULL AND btrim(p_target) = '') THEN
        RAISE EXCEPTION 'mbos: PANIC target must be NULL for L3 and set for L1/L2' USING ERRCODE = 'MB004';
    END IF;
    IF coalesce(btrim(p_reason), '') = '' THEN
        RAISE EXCEPTION 'mbos: PANIC change needs a reason' USING ERRCODE = 'MB004';
    END IF;

    PERFORM pg_advisory_xact_lock(7340004005);
    SELECT coalesce(max(revision), 0) + 1 INTO next_rev FROM mbos.panic_state;
    SELECT * INTO s FROM mbos.panic_read();
    stamp := jsonb_build_object('changed_at', mbos.utc_iso(now()), 'changed_by', p_actor->>'id', 'reason', p_reason);
    IF s.readable THEN
        SELECT p.body INTO before FROM mbos.panic_state p ORDER BY p.revision DESC LIMIT 1;
        after := before - 'checksum';
    ELSE   -- an unreadable or empty state is rebuilt FROZEN, never repaired into RUNNING
        before := NULL;
        after := jsonb_build_object('schema', 'mbos.governance.panic/1', 'agents', '{}'::jsonb,
                     'capabilities', '{}'::jsonb,
                     'global', jsonb_build_object('state', 'FROZEN', 'changed_at', mbos.utc_iso(now()),
                                                  'changed_by', 'system', 'reason', 'rebuilt from: ' || s.error));
    END IF;
    IF p_level = 'L3' THEN
        after := jsonb_set(after, '{global}',
                           jsonb_build_object('state', CASE WHEN p_engage THEN 'FROZEN' ELSE 'RUNNING' END) || stamp);
    ELSE
        key := CASE p_level WHEN 'L1' THEN 'agents' ELSE 'capabilities' END;
        after := jsonb_set(after, ARRAY[key], CASE WHEN p_engage THEN (after->key) || jsonb_build_object(p_target, stamp)
                                                   ELSE (after->key) - p_target END);
    END IF;
    sealed := mbos.panic_seal(after || jsonb_build_object('revision', next_rev));

    INSERT INTO mbos.panic_state (revision, global_state, body, level, target, engage, actor, reason)
    VALUES (next_rev, sealed->'global'->>'state', sealed, p_level, p_target, p_engage, p_actor, p_reason);
    rc := mbos.append_receipt(jsonb_build_object(
        'type', 'KILL_SWITCH_CHANGED', 'actor', p_actor, 'entity_type', 'panic_state', 'entity_id', 'panic:' || next_rev,
        'intent', format('PANIC %s %s%s: %s', p_level, CASE WHEN p_engage THEN 'engage' ELSE 'release' END,
                         coalesce(' ' || p_target, ''), p_reason),
        'effect', 'update', 'idempotency_key', p_idempotency_key, 'provenance_ids', to_jsonb(p_provenance_ids),
        'before_state', before, 'after_state', sealed));

    -- L3 engage: requests approved but not started are cancelled now, each with its own receipt.
    IF p_level = 'L3' AND p_engage THEN
        FOR a IN SELECT * FROM mbos.action_requests WHERE status IN ('approved','auto_approved')
                 ORDER BY created_at FOR UPDATE LOOP
            UPDATE mbos.action_requests SET status = 'cancelled_by_freeze' WHERE action_request_id = a.action_request_id;
            PERFORM mbos.append_receipt(jsonb_build_object(
                'type', 'KILL_SWITCH_CHANGED', 'actor', p_actor, 'item_id', a.item_id,
                'action_request_id', a.action_request_id, 'capability', a.capability, 'payload_hash', a.payload_hash,
                'entity_type', 'action_request', 'entity_id', a.action_request_id, 'effect', 'none',
                'intent', 'L3 PANIC: cancel unstarted approved request (' || p_reason || ')',
                'idempotency_key', p_idempotency_key || ':cancel:' || a.action_request_id,
                'provenance_ids', to_jsonb(p_provenance_ids),
                'before_state', jsonb_build_object('status', a.status),
                'after_state', jsonb_build_object('status', 'cancelled_by_freeze', 'panic_revision', next_rev)));
        END LOOP;
    END IF;
    RETURN rc.receipt_id;
END $$;

-- Back-compat names from 0005 delegate to the single rule set.
CREATE OR REPLACE FUNCTION mbos.panic_mutate(p_level text, p_target text, p_engage boolean, p_actor jsonb, p_reason text,
                                             p_provenance_ids text[], p_idempotency_key text) RETURNS text
LANGUAGE sql AS $$ SELECT mbos.panic_set(p_level, p_target, p_engage, p_actor, p_reason, p_provenance_ids, p_idempotency_key) $$;

CREATE VIEW mbos.panic_events AS
    SELECT p.revision, p.created_at AS ts, p.level, p.target, p.engage, p.actor, p.reason, r.receipt_id,
           p.global_state, p.body->>'checksum' AS checksum
    FROM mbos.panic_state p
    LEFT JOIN mbos.receipts r ON r.type = 'KILL_SWITCH_CHANGED' AND r.entity_type = 'panic_state'
                             AND r.entity_id = 'panic:' || p.revision;

-- Every freeze in force. FAIL CLOSED: an empty, unreadable or tampered state shows as an L3 row.
CREATE VIEW mbos.panic_current AS
    WITH s AS (SELECT * FROM mbos.panic_read()),
         b AS (SELECT p.body FROM mbos.panic_state p ORDER BY p.revision DESC LIMIT 1)
    SELECT 'L3'::text AS level, NULL::text AS target,
           CASE WHEN s.readable THEN (SELECT body->'global' FROM b) ELSE NULL END AS since,
           CASE WHEN s.readable THEN 'FROZEN' ELSE 'UNREADABLE: ' || s.error END AS reason, s.revision
    FROM s WHERE NOT s.readable OR s.global_state <> 'RUNNING'
    UNION ALL
    SELECT 'L1', e.key, e.value, e.value->>'reason', s.revision FROM s, jsonb_each(s.agents) e WHERE s.readable
    UNION ALL
    SELECT 'L2', e.key, e.value, e.value->>'reason', s.revision FROM s, jsonb_each(s.capabilities) e WHERE s.readable;

-- Bootstrap FROZEN (05 §1): a fresh database starts with one L3 engage event; releasing is Michael's act.
DO $$
DECLARE pid text;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM mbos.panic_state) THEN
        pid := mbos.record_provenance(jsonb_build_object('actor_type', 'system', 'agent_name', 'agent-04-state',
                   'basis', 'FACT', 'tool_name', 'mbos_state.migrate', 'tool_version', '0007'));
        PERFORM mbos.panic_set('L3', NULL, true, '{"type":"system","id":"mbos-migrate"}'::jsonb, 'initial state',
                               ARRAY[pid], 'panic:bootstrap:0007');
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- §2 effector_calls as the execution claim
-- ---------------------------------------------------------------------------
-- Blanket insert-only is replaced below by a guard that allows exactly one finishing update.
DROP TRIGGER zz_append_only_row ON mbos.effector_calls;
ALTER TABLE mbos.effector_calls
    ADD COLUMN state text NOT NULL DEFAULT 'executed' CHECK (state IN ('executing','executed','failed')),
    ADD COLUMN claimed_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN finished_at timestamptz,
    ALTER COLUMN provider DROP NOT NULL,
    ALTER COLUMN provider_msg_id DROP NOT NULL,
    ALTER COLUMN request DROP NOT NULL,
    ALTER COLUMN response DROP NOT NULL;
-- Rows written by 0005-style single-shot calls were finished when created.
UPDATE mbos.effector_calls SET claimed_at = created_at, finished_at = created_at;
ALTER TABLE mbos.effector_calls
    ADD CONSTRAINT effector_calls_one_per_request UNIQUE (action_request_id),
    ADD CONSTRAINT effector_calls_finished CHECK ((state = 'executing') = (finished_at IS NULL)),
    ADD CONSTRAINT effector_calls_executed_has_response CHECK (state <> 'executed' OR response IS NOT NULL);
COMMENT ON TABLE mbos.effector_calls IS
    'Execution claim + effector record (A5 anchor). Insert state=executing in the same transaction as the '
    'ACTION_EXECUTING receipt; finish exactly once to executed|failed. A row stuck in executing is never deleted: '
    'reconciliation reads it. Single-shot inserts (state defaults to executed) remain valid.';

-- Finished-at for single-shot inserts.
CREATE FUNCTION mbos.effector_calls_stamp() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.state <> 'executing' THEN NEW.finished_at := coalesce(NEW.finished_at, now()); END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER ab_effector_calls_stamp BEFORE INSERT ON mbos.effector_calls
    FOR EACH ROW EXECUTE FUNCTION mbos.effector_calls_stamp();

-- Exactly one update executing -> executed|failed; never delete.
CREATE FUNCTION mbos.effector_calls_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'mbos: effector calls are never deleted' USING ERRCODE = 'MB001';
    END IF;
    IF OLD.state <> 'executing' OR NEW.state NOT IN ('executed','failed') THEN
        RAISE EXCEPTION 'mbos: effector call % is %; only executing -> executed|failed, once', OLD.idempotency_key, OLD.state
            USING ERRCODE = 'MB001';
    END IF;
    IF (NEW.seq, NEW.idempotency_key, NEW.action_request_id, NEW.capability, NEW.dry_run, NEW.request, NEW.claimed_at)
       IS DISTINCT FROM
       (OLD.seq, OLD.idempotency_key, OLD.action_request_id, OLD.capability, OLD.dry_run, OLD.request, OLD.claimed_at) THEN
        RAISE EXCEPTION 'mbos: effector claim identity is immutable' USING ERRCODE = 'MB001';
    END IF;
    NEW.finished_at := now();
    RETURN NEW;
END $$;
CREATE TRIGGER zz_effector_calls_guard BEFORE UPDATE OR DELETE ON mbos.effector_calls
    FOR EACH ROW EXECUTE FUNCTION mbos.effector_calls_guard();

-- Claim before calling the effector. replayed=true means a claim already exists: do NOT call again; if its
-- state is still `executing` the caller must reconcile with the provider (05 G4), never re-send blindly.
CREATE FUNCTION mbos.effector_claim(p_action_request_id text, p_request jsonb DEFAULT NULL)
RETURNS TABLE (state text, response jsonb, replayed boolean) LANGUAGE plpgsql AS $$
DECLARE a mbos.action_requests; c mbos.effector_calls;
BEGIN
    SELECT * INTO a FROM mbos.action_requests WHERE action_request_id = p_action_request_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'mbos: action request % not found', p_action_request_id USING ERRCODE = 'MB404'; END IF;
    SELECT * INTO c FROM mbos.effector_calls WHERE idempotency_key = a.idempotency_key;
    IF FOUND THEN RETURN QUERY SELECT c.state, c.response, true; RETURN; END IF;
    INSERT INTO mbos.effector_calls (idempotency_key, action_request_id, capability, dry_run, request, state)
    VALUES (a.idempotency_key, a.action_request_id, a.capability, true, p_request, 'executing');
    RETURN QUERY SELECT 'executing'::text, NULL::jsonb, false;
END $$;

CREATE FUNCTION mbos.effector_finish(p_action_request_id text, p_state text, p_provider text,
                                     p_provider_msg_id text, p_response jsonb) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE c mbos.effector_calls;
BEGIN
    SELECT * INTO c FROM mbos.effector_calls WHERE action_request_id = p_action_request_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'mbos: no execution claim for %', p_action_request_id USING ERRCODE = 'MB404';
    END IF;
    IF c.state <> 'executing' THEN
        IF c.state = p_state THEN RETURN c.response; END IF;   -- idempotent replay
        RAISE EXCEPTION 'mbos: claim for % already %', p_action_request_id, c.state USING ERRCODE = 'MB409';
    END IF;
    UPDATE mbos.effector_calls SET state = p_state, provider = p_provider, provider_msg_id = p_provider_msg_id,
                                   response = p_response
    WHERE idempotency_key = c.idempotency_key;
    RETURN p_response;
END $$;

-- ---------------------------------------------------------------------------
-- §4 budget: modes, zero-cost, multi-cap reserve, policy-day exposure
-- ---------------------------------------------------------------------------
-- Sub-cent costs (SMS) must not round: widen to 6 decimals (05 request). The view depends on the column.
DROP VIEW mbos.v_budget_reservations;
ALTER TABLE mbos.budget_ledger
    ALTER COLUMN amount TYPE numeric(14,6),
    ALTER COLUMN cap_applied TYPE numeric(14,6),
    DROP CONSTRAINT budget_ledger_amount_check,
    ADD CONSTRAINT budget_ledger_amount_check CHECK (amount >= 0),
    ADD COLUMN mode text NOT NULL DEFAULT 'dry_run' CHECK (mode IN ('dry_run','live')),
    -- MVP / MICHAEL_DECISIONS #1: real-world spend is deny-all. Lifting this needs a migration + decision.
    ADD CONSTRAINT budget_wave1_live_is_zero CHECK (mode = 'dry_run' OR amount = 0);

CREATE OR REPLACE FUNCTION mbos.budget_before_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE res mbos.budget_ledger; settled numeric;
BEGIN
    IF NEW.kind = 'reserve' THEN RETURN NEW; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('mbos.budget.res:' || NEW.reservation_id, 0));
    SELECT * INTO res FROM mbos.budget_ledger WHERE entry_id = NEW.reservation_id;
    IF res.kind IS DISTINCT FROM 'reserve' OR res.action_request_id <> NEW.action_request_id
       OR res.category <> NEW.category OR res.currency <> NEW.currency OR res.mode <> NEW.mode THEN
        RAISE EXCEPTION 'mbos: % must reference a matching reservation (same request, category, currency, mode)', NEW.kind
            USING ERRCODE = 'MB006';
    END IF;
    SELECT coalesce(sum(amount), 0) INTO settled FROM mbos.budget_ledger WHERE reservation_id = res.entry_id;
    IF settled + NEW.amount > res.amount THEN
        RAISE EXCEPTION 'mbos: % of % exceeds remaining reservation % (reserved %, settled %)',
            NEW.kind, NEW.amount, res.entry_id, res.amount, settled USING ERRCODE = 'MB006';
    END IF;
    RETURN NEW;
END $$;

CREATE VIEW mbos.v_budget_reservations AS
    SELECT r.entry_id AS reservation_id, r.ts, r.category, r.currency, r.mode, r.action_request_id, r.amount AS reserved,
           coalesce(sum(s.amount) FILTER (WHERE s.kind = 'commit'), 0)  AS committed,
           coalesce(sum(s.amount) FILTER (WHERE s.kind = 'release'), 0) AS released,
           r.amount - coalesce(sum(s.amount), 0)                        AS outstanding
    FROM mbos.budget_ledger r
    LEFT JOIN mbos.budget_ledger s ON s.reservation_id = r.entry_id
    WHERE r.kind = 'reserve'
    GROUP BY r.entry_id;

-- Reserved minus released within the policy day [local midnight, +1 day) of p_tz, over a BUCKET of
-- categories (05 policy buckets, e.g. comms = message, sms, phone_call, email). NULL = all categories.
CREATE FUNCTION mbos.budget_exposure_day(p_categories text[], p_currency text, p_mode text, p_tz text,
                                         p_at timestamptz DEFAULT now()) RETURNS numeric
LANGUAGE sql STABLE AS $$
    WITH w AS (SELECT (date_trunc('day', p_at AT TIME ZONE p_tz)) AT TIME ZONE p_tz AS lo)
    SELECT coalesce(sum(CASE kind WHEN 'reserve' THEN amount WHEN 'release' THEN -amount ELSE 0 END), 0)
    FROM mbos.budget_ledger, w
    WHERE (p_categories IS NULL OR category = ANY (p_categories)) AND currency = p_currency AND mode = p_mode
      AND ts >= w.lo AND ts < w.lo + interval '1 day'
$$;

-- Velocity: reservations made in the last hour over the bucket, minus what of them was released
-- (zero-amount reservations count as rows but add 0).
CREATE FUNCTION mbos.budget_velocity_hour(p_categories text[], p_currency text, p_mode text,
                                          p_at timestamptz DEFAULT now()) RETURNS numeric
LANGUAGE sql STABLE AS $$
    SELECT coalesce(sum(r.amount - coalesce((SELECT sum(x.amount) FROM mbos.budget_ledger x
                                             WHERE x.reservation_id = r.entry_id AND x.kind = 'release'), 0)), 0)
    FROM mbos.budget_ledger r
    WHERE r.kind = 'reserve' AND (p_categories IS NULL OR r.category = ANY (p_categories))
      AND r.currency = p_currency AND r.mode = p_mode AND r.ts > p_at - interval '1 hour'
$$;

-- One lock per currency serializes every reservation (old single-cap function included), so no
-- combination of concurrent approvals can overshoot any cap.
CREATE OR REPLACE FUNCTION mbos.budget_lock(p_currency text) RETURNS void
LANGUAGE sql AS $$ SELECT pg_advisory_xact_lock(hashtextextended('mbos.budget.global:' || p_currency, 0)) $$;

CREATE FUNCTION mbos.budget_reserve_caps(p_areq_id text, p_amount numeric, p_currency text, p_caps jsonb,
                                         p_mode text, p_actor jsonb, p_intent text, p_provenance_ids text[],
                                         p_idempotency_key text) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE
    a mbos.action_requests; prev mbos.receipts; e mbos.budget_ledger; k text; tz text; bucket text[];
    day_cat numeric; day_all numeric; hour_all numeric;
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
                                          'last_hour', hour_all + p_amount),
        'details', jsonb_build_object('kind', 'money', 'dry_run', p_mode = 'dry_run')));
    RETURN e.entry_id;
END $$;

-- The 0003 single-cap reserve and settle: same lock as budget_reserve_caps; settle inherits the mode.
CREATE OR REPLACE FUNCTION mbos.budget_reserve(p_areq_id text, p_amount numeric, p_currency text, p_cap numeric,
                                               p_actor jsonb, p_intent text, p_provenance_ids text[], p_idempotency_key text)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE a mbos.action_requests; prev mbos.receipts; exposure numeric; e mbos.budget_ledger;
BEGIN
    prev := mbos.idempotent_receipt(p_idempotency_key, 'BUDGET_RESERVED');
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.entity_id; END IF;
    IF p_cap IS NULL THEN
        RAISE EXCEPTION 'mbos: no budget cap supplied — reservation denied (fail-closed)' USING ERRCODE = 'MB006';
    END IF;
    SELECT * INTO a FROM mbos.action_requests WHERE action_request_id = p_areq_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'mbos: action request % not found', p_areq_id USING ERRCODE = 'MB404'; END IF;
    PERFORM mbos.budget_lock(p_currency);
    exposure := mbos.budget_exposure(a.category, p_currency);
    IF exposure + p_amount > p_cap THEN
        RAISE EXCEPTION 'mbos: reserving % % would exceed the % cap % (current exposure %)',
            p_amount, p_currency, a.category, p_cap, exposure USING ERRCODE = 'MB006';
    END IF;
    INSERT INTO mbos.budget_ledger (kind, category, action_request_id, amount, currency, cap_applied, provenance_ids)
    VALUES ('reserve', a.category, a.action_request_id, p_amount, p_currency, p_cap, p_provenance_ids)
    RETURNING * INTO e;
    PERFORM mbos.append_receipt(jsonb_build_object(
        'type', 'BUDGET_RESERVED', 'actor', p_actor, 'intent', p_intent, 'item_id', a.item_id,
        'action_request_id', a.action_request_id, 'capability', a.capability, 'payload_hash', a.payload_hash,
        'entity_type', 'budget_entry', 'entity_id', e.entry_id, 'effect', 'none', 'idempotency_key', p_idempotency_key,
        'provenance_ids', to_jsonb(p_provenance_ids),
        'budget_effect', jsonb_build_object('category', e.category, 'amount', e.amount, 'currency', e.currency),
        'after_state', jsonb_build_object('kind', 'reserve', 'mode', e.mode, 'exposure', exposure + p_amount, 'cap', p_cap),
        'details', jsonb_build_object('kind', 'money', 'dry_run', true)));
    RETURN e.entry_id;
END $$;

CREATE OR REPLACE FUNCTION mbos.budget_settle(p_reservation_id text, p_kind text, p_amount numeric, p_actor jsonb,
                                              p_intent text, p_provenance_ids text[], p_idempotency_key text)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE res mbos.budget_ledger; a mbos.action_requests; prev mbos.receipts; e mbos.budget_ledger; amt numeric; rtype text;
BEGIN
    IF p_kind NOT IN ('commit','release') THEN
        RAISE EXCEPTION 'mbos: settle kind must be commit or release' USING ERRCODE = 'MB006';
    END IF;
    rtype := CASE p_kind WHEN 'commit' THEN 'BUDGET_COMMITTED' ELSE 'BUDGET_RELEASED' END;
    prev := mbos.idempotent_receipt(p_idempotency_key, rtype);
    IF prev.receipt_id IS NOT NULL THEN RETURN prev.entity_id; END IF;
    SELECT * INTO res FROM mbos.budget_ledger WHERE entry_id = p_reservation_id AND kind = 'reserve';
    IF NOT FOUND THEN RAISE EXCEPTION 'mbos: reservation % not found', p_reservation_id USING ERRCODE = 'MB404'; END IF;
    SELECT * INTO a FROM mbos.action_requests WHERE action_request_id = res.action_request_id;
    amt := coalesce(p_amount, res.amount - (SELECT coalesce(sum(amount), 0) FROM mbos.budget_ledger
                                           WHERE reservation_id = res.entry_id));
    INSERT INTO mbos.budget_ledger (kind, category, action_request_id, reservation_id, amount, currency, provenance_ids, mode)
    VALUES (p_kind, res.category, res.action_request_id, res.entry_id, amt, res.currency, p_provenance_ids, res.mode)
    RETURNING * INTO e;
    PERFORM mbos.append_receipt(jsonb_build_object(
        'type', rtype, 'actor', p_actor, 'intent', p_intent, 'item_id', a.item_id,
        'action_request_id', a.action_request_id, 'capability', a.capability, 'payload_hash', a.payload_hash,
        'entity_type', 'budget_entry', 'entity_id', e.entry_id, 'effect', 'none', 'idempotency_key', p_idempotency_key,
        'provenance_ids', to_jsonb(p_provenance_ids),
        'budget_effect', jsonb_build_object('category', e.category, 'amount', e.amount, 'currency', e.currency),
        'after_state', jsonb_build_object('kind', p_kind, 'mode', e.mode, 'reservation_id', res.entry_id),
        'details', jsonb_build_object('kind', 'money', 'dry_run', e.mode = 'dry_run')));
    RETURN e.entry_id;
END $$;

-- ---------------------------------------------------------------------------
-- §7 grants. Agents (agent_write) get no PANIC mutation, no claim functions, no set_action_status.
-- ---------------------------------------------------------------------------
REVOKE EXECUTE ON FUNCTION mbos.panic_set(text, text, boolean, jsonb, text, text[], text),
    mbos.effector_claim(text, jsonb), mbos.effector_finish(text, text, text, text, jsonb),
    mbos.budget_exposure_day(text[], text, text, text, timestamptz), mbos.budget_lock(text),
    mbos.budget_velocity_hour(text[], text, text, timestamptz),
    mbos.budget_reserve_caps(text, numeric, text, jsonb, text, jsonb, text, text[], text),
    mbos.effector_calls_stamp(), mbos.effector_calls_guard() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION mbos.panic_mutate(text, text, boolean, jsonb, text, text[], text),
    mbos.panic_init(jsonb, text, text[], text, text), mbos._panic_write(jsonb, jsonb, jsonb, text, text[], text)
    FROM agent_write;
REVOKE INSERT ON mbos.panic_state FROM agent_write;

GRANT SELECT ON mbos.panic_events, mbos.panic_current TO agent_read, agent_write, gateway, approver, policy_admin;
GRANT INSERT ON mbos.panic_state TO approver;
GRANT EXECUTE ON FUNCTION mbos.panic_set(text, text, boolean, jsonb, text, text[], text),
    mbos.panic_mutate(text, text, boolean, jsonb, text, text[], text)
    TO gateway, approver, policy_admin;
GRANT EXECUTE ON FUNCTION mbos.record_provenance(jsonb), mbos.append_receipt(jsonb) TO approver;
GRANT UPDATE (status) ON mbos.action_requests TO policy_admin;   -- L3 engage cancels unstarted requests

GRANT UPDATE (state, provider, provider_msg_id, response, finished_at) ON mbos.effector_calls TO gateway;
GRANT EXECUTE ON FUNCTION mbos.effector_claim(text, jsonb), mbos.effector_finish(text, text, text, text, jsonb)
    TO gateway;

GRANT SELECT ON mbos.v_budget_reservations TO agent_read, agent_write, gateway, approver, policy_admin;
GRANT EXECUTE ON FUNCTION mbos.budget_exposure_day(text[], text, text, text, timestamptz),
    mbos.budget_velocity_hour(text[], text, text, timestamptz)
    TO agent_read, agent_write, gateway, approver, policy_admin;
GRANT EXECUTE ON FUNCTION mbos.budget_lock(text),
    mbos.budget_reserve_caps(text, numeric, text, jsonb, text, jsonb, text, text[], text) TO gateway;
GRANT EXECUTE ON FUNCTION mbos.propose_action(jsonb, jsonb, text, text) TO gateway;
GRANT INSERT ON mbos.action_requests TO gateway;
