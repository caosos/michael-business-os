-- 0017_capital_ledger.sql — READY_QUEUE D-18: the capital ledger (ADR-0013; Agent 01's mission.schema.json, A-23).
--
--   mbos.mission          the weekly mission (target / hours may be NULL = UNKNOWN, never guessed). Versioned, insert-only.
--   mbos.capital_ledger   insert-only entries DERIVED FROM RECEIPTS by one trigger (no role can insert directly).
--   mbos.v_capital_position / mbos.capital_position_document()   the position, in the schema's capital_ledger shape.
--   mbos.capital_replay() / mbos.capital_verify()               rebuild the ledger from receipts alone and compare.
--
-- Capital model (docs/product/DEAL_SNIFFER_START_HERE.md §1):
--   fund      owner sets the bankroll                       protected_principal += amount
--   deploy    a committed purchase/money spend              capital_deployed    += amount            (per item)
--   close     the item's closing outcome, recorded by Michael:
--               capital_deployed -= basis (principal returns), realized_profit += net
--               net > 0: profit becomes earned working capital
--               net < 0: a LOSS consumes earned working capital FIRST; the remainder is recorded as principal_impairment
--                        and flagged. protected_principal stays the owner's original contribution (no silent rewrite).
--               Internally one signed position X = sum(net) - withdrawals is kept; the schema's two fields are
--               earned_working_capital = max(X, 0) and principal_impairment = max(-X, 0), so impairment can only exist
--               while earned is 0 (Agent 01's invariant). Later profit repairs the impairment first, because the
--               invariant leaves it no other place to go; Michael's rebuild decision is an explicit `fund`.
--   withdraw  owner takes earned money out                  earned_working_capital -= amount (never principal)
--   available_to_deploy = protected_principal - principal_impairment + earned_working_capital - capital_deployed   (schema invariant)
--
-- Safety properties:
--   * No entry without a receipt: entries are produced only by an AFTER INSERT trigger on mbos.receipts, in the
--     receipt's own transaction, and cite it (source_receipt_id).
--   * Capital cannot be minted by an agent: fund / withdraw / close entries need an approver-role session AND (close) a
--     HUMAN-recorded outcome; deploy needs gateway/approver. A forged receipt from any other role is refused.
--   * A deploy that exceeds available_to_deploy is refused: the budget commit and its receipt roll back (fail closed).
--   * The ledger is INACTIVE until Michael funds it. Until then nothing is accounted and nothing is refused, so existing
--     budget flows are unchanged.
--   * Wave one is dry-run accounting only (mode CHECK), like budget_ledger.

-- ---------------------------------------------------------------------------
-- Data tables, not code constants
-- ---------------------------------------------------------------------------
CREATE TABLE mbos.capital_deploy_categories (category text PRIMARY KEY);
INSERT INTO mbos.capital_deploy_categories VALUES ('purchase'), ('money');
CREATE TABLE mbos.capital_closing_kinds (kind text PRIMARY KEY);   -- outcome kinds that close an item's capital
INSERT INTO mbos.capital_closing_kinds VALUES ('flip_sold'), ('flip_unsold_salvaged'), ('flip_repair_failed'), ('service_paid');
SELECT mbos.make_append_only('mbos.capital_deploy_categories');
SELECT mbos.make_append_only('mbos.capital_closing_kinds');

-- ---------------------------------------------------------------------------
-- Mission (schema: mission)
-- ---------------------------------------------------------------------------
CREATE TABLE mbos.mission (
    seq               bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    mission_id        text PRIMARY KEY DEFAULT mbos.new_id('msn') CHECK (mission_id ~ '^msn_[0-9A-HJKMNP-TV-Z]{26}$'),
    mission_version   text NOT NULL DEFAULT '1.0.0' CHECK (mission_version = '1.0.0'),
    period_start      date NOT NULL,
    period_end        date NOT NULL,
    weekly_target_usd numeric(14,2) CHECK (weekly_target_usd IS NULL OR weekly_target_usd >= 0),   -- NULL = UNKNOWN
    hours_available   numeric(7,2)  CHECK (hours_available IS NULL OR hours_available >= 0),       -- NULL = UNKNOWN
    notes             text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    created_by        text NOT NULL CHECK (btrim(created_by) <> ''),
    provenance_ids    text[] NOT NULL CHECK (cardinality(provenance_ids) >= 1),
    CONSTRAINT mission_period_ordered CHECK (period_end >= period_start)
);
SELECT mbos.make_append_only('mbos.mission');

CREATE FUNCTION mbos.mission_require_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM mbos.require_receipt(ARRAY['CONFIG_VERSION_BUMPED'], 'entity_id', NEW.mission_id);
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER zz_mission_receipt AFTER INSERT ON mbos.mission
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION mbos.mission_require_receipt();

-- Michael sets (or revises) the mission. A revision is a new row; the latest wins.
CREATE FUNCTION mbos.set_mission(p_mission jsonb, p_actor jsonb, p_intent text, p_provenance_ids text[],
                                 p_idempotency_key text) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE prev mbos.receipts; m mbos.mission; id text;
BEGIN
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

-- The current mission in the schema's shape. NULLs stay NULL (UNKNOWN is never replaced by a guess).
CREATE VIEW mbos.v_mission_current AS
    SELECT m.mission_id, m.seq, jsonb_strip_nulls(jsonb_build_object(
               'mission_version', m.mission_version,
               'period', jsonb_build_object('start', m.period_start::text, 'end', m.period_end::text),
               'notes', m.notes))
           || jsonb_build_object('weekly_target_usd', m.weekly_target_usd, 'hours_available', m.hours_available) AS doc
    FROM mbos.mission m
    WHERE m.seq = (SELECT max(seq) FROM mbos.mission);

-- ---------------------------------------------------------------------------
-- Ledger entries (derived, insert-only)
-- ---------------------------------------------------------------------------
CREATE TABLE mbos.capital_ledger (
    seq               bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    entry_id          text PRIMARY KEY DEFAULT mbos.new_id('cap') CHECK (entry_id ~ '^cap_[0-9A-HJKMNP-TV-Z]{26}$'),
    ts                timestamptz NOT NULL DEFAULT now(),
    mode              text NOT NULL DEFAULT 'dry_run',
    kind              text NOT NULL CHECK (kind IN ('fund','withdraw','deploy','close')),
    item_id           text REFERENCES mbos.items,
    amount            numeric(14,2) NOT NULL CHECK (amount >= 0),   -- fund/withdraw/deploy: the money; close: principal returned (= basis)
    basis             numeric(14,2) CHECK (basis IS NULL OR basis >= 0),
    net               numeric(14,2),                                 -- close only: realized net (profit > 0, loss < 0)
    currency          text NOT NULL DEFAULT 'USD' CHECK (currency = 'USD'),
    source_receipt_id text NOT NULL UNIQUE REFERENCES mbos.receipts (receipt_id),
    provenance_ids    text[] NOT NULL CHECK (cardinality(provenance_ids) >= 1),
    -- Wave one: dry-run accounting only. Going live is a reviewed migration plus a Michael decision.
    CONSTRAINT capital_wave1_dry_run_only CHECK (mode = 'dry_run'),
    CONSTRAINT capital_fund_positive      CHECK (kind NOT IN ('fund','withdraw') OR amount > 0),
    CONSTRAINT capital_item_kinds         CHECK ((kind IN ('deploy','close')) = (item_id IS NOT NULL)),
    CONSTRAINT capital_close_fields       CHECK ((kind = 'close') = (basis IS NOT NULL AND net IS NOT NULL)),
    CONSTRAINT capital_close_returns_basis CHECK (kind <> 'close' OR amount = basis)
);
CREATE UNIQUE INDEX capital_one_close_per_item ON mbos.capital_ledger (mode, item_id) WHERE kind = 'close';
CREATE INDEX capital_item_idx ON mbos.capital_ledger (item_id) WHERE item_id IS NOT NULL;
SELECT mbos.make_append_only('mbos.capital_ledger');

-- Entries may only come from the derivation trigger.
CREATE FUNCTION mbos.capital_ledger_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF coalesce(current_setting('mbos.capital_derive', true), '') <> 'on' THEN
        RAISE EXCEPTION 'mbos: capital_ledger entries are derived from receipts only; no direct insert' USING ERRCODE = 'MB001';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER aa_capital_ledger_guard BEFORE INSERT ON mbos.capital_ledger
    FOR EACH ROW EXECUTE FUNCTION mbos.capital_ledger_guard();

-- ---------------------------------------------------------------------------
-- The ONE derivation rule, used by the trigger and by replay. Pure: it reads only the receipt and the state passed in.
-- Returns NULL when the receipt does not move capital. Raises (MB006) when it must be refused.
-- p_enforce_roles: the INSERT-time gate on the writing session (session_user). Replay passes false: the original writer
-- is not recoverable from the receipt, and a stored entry already passed the gate when it was written.
-- ---------------------------------------------------------------------------
CREATE FUNCTION mbos.capital_entry_for(r mbos.receipts, p_active boolean, p_available numeric, p_earned numeric,
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
        IF p_enforce_roles AND NOT (is_approver OR owner) THEN
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

-- Current state from the entries (the trigger's input).
CREATE FUNCTION mbos.capital_state(p_item_id text DEFAULT NULL,
    OUT active boolean, OUT principal numeric, OUT earned numeric, OUT deployed numeric, OUT available numeric,
    OUT item_deployed numeric, OUT item_closed boolean)
LANGUAGE sql STABLE AS $$
    SELECT coalesce(bool_or(kind = 'fund'), false),
           coalesce(sum(amount) FILTER (WHERE kind = 'fund'), 0),
           coalesce(sum(net) FILTER (WHERE kind = 'close'), 0) - coalesce(sum(amount) FILTER (WHERE kind = 'withdraw'), 0),
           coalesce(sum(amount) FILTER (WHERE kind = 'deploy'), 0) - coalesce(sum(basis) FILTER (WHERE kind = 'close'), 0),
           coalesce(sum(amount) FILTER (WHERE kind = 'fund'), 0)
             + coalesce(sum(net) FILTER (WHERE kind = 'close'), 0) - coalesce(sum(amount) FILTER (WHERE kind = 'withdraw'), 0)
             - (coalesce(sum(amount) FILTER (WHERE kind = 'deploy'), 0) - coalesce(sum(basis) FILTER (WHERE kind = 'close'), 0)),
           coalesce(sum(amount) FILTER (WHERE kind = 'deploy' AND item_id = p_item_id), 0)
             - coalesce(sum(basis) FILTER (WHERE kind = 'close' AND item_id = p_item_id), 0),
           coalesce(bool_or(kind = 'close' AND item_id = p_item_id), false)
    FROM mbos.capital_ledger
$$;

-- The derivation trigger. SECURITY DEFINER so no role needs INSERT on the ledger; the role checks above use
-- session_user, which a definer function does not change. The receipt chain's advisory lock (held to commit by the
-- receipt insert) already serializes every receipt writer, so reading the state here cannot race.
CREATE FUNCTION mbos.receipts_to_capital() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, mbos AS $$
DECLARE st record; e jsonb;
BEGIN
    IF NOT (NEW.type IN ('CONFIG_VERSION_BUMPED', 'BUDGET_COMMITTED', 'OUTCOME_RECORDED')) THEN RETURN NULL; END IF;
    SELECT * INTO st FROM mbos.capital_state(NEW.item_id);
    e := mbos.capital_entry_for(NEW, st.active, st.available, st.earned, st.item_deployed, st.item_closed, true);
    IF e IS NULL THEN RETURN NULL; END IF;
    PERFORM set_config('mbos.capital_derive', 'on', true);
    INSERT INTO mbos.capital_ledger (kind, item_id, amount, basis, net, source_receipt_id, provenance_ids)
    VALUES (e->>'kind', e->>'item_id', (e->>'amount')::numeric, (e->>'basis')::numeric, (e->>'net')::numeric,
            NEW.receipt_id, NEW.provenance_ids);
    PERFORM set_config('mbos.capital_derive', 'off', true);
    RETURN NULL;
END $$;
CREATE TRIGGER zz_receipts_capital AFTER INSERT ON mbos.receipts
    FOR EACH ROW EXECUTE FUNCTION mbos.receipts_to_capital();

-- ---------------------------------------------------------------------------
-- Owner entry points (approver only): they write the receipt; the trigger derives the entry.
-- ---------------------------------------------------------------------------
CREATE FUNCTION mbos._capital_owner_receipt(p_type text, p_amount numeric, p_actor jsonb, p_intent text,
                                            p_provenance_ids text[], p_idempotency_key text) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE prev mbos.receipts; rc mbos.receipts;
BEGIN
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

CREATE FUNCTION mbos.capital_fund(p_amount numeric, p_actor jsonb, p_intent text, p_provenance_ids text[],
                                  p_idempotency_key text) RETURNS text
LANGUAGE sql AS $$ SELECT mbos._capital_owner_receipt('capital_fund', p_amount, p_actor, p_intent, p_provenance_ids, p_idempotency_key) $$;

CREATE FUNCTION mbos.capital_withdraw(p_amount numeric, p_actor jsonb, p_intent text, p_provenance_ids text[],
                                      p_idempotency_key text) RETURNS text
LANGUAGE sql AS $$ SELECT mbos._capital_owner_receipt('capital_withdraw', p_amount, p_actor, p_intent, p_provenance_ids, p_idempotency_key) $$;

-- ---------------------------------------------------------------------------
-- Position (schema: capital_ledger) and its document
-- ---------------------------------------------------------------------------
CREATE VIEW mbos.v_capital_position AS
    WITH s AS (
        SELECT l.mode,
               coalesce(sum(l.amount) FILTER (WHERE l.kind = 'fund'), 0)                          AS principal,
               coalesce(sum(l.net) FILTER (WHERE l.kind = 'close'), 0)
                 - coalesce(sum(l.amount) FILTER (WHERE l.kind = 'withdraw'), 0)                  AS x,        -- signed earned position
               coalesce(sum(l.amount) FILTER (WHERE l.kind = 'deploy'), 0)
                 - coalesce(sum(l.basis) FILTER (WHERE l.kind = 'close'), 0)                      AS deployed,
               coalesce(sum(l.net) FILTER (WHERE l.kind = 'close'), 0)                            AS realized,
               count(DISTINCT l.item_id) FILTER (WHERE l.kind = 'deploy'
                   AND NOT EXISTS (SELECT 1 FROM mbos.capital_ledger c WHERE c.kind = 'close' AND c.item_id = l.item_id)) AS open_items,
               max(l.ts)                                                                          AS as_of
        FROM mbos.capital_ledger l
        GROUP BY l.mode
        HAVING bool_or(l.kind = 'fund')
    )
    SELECT s.mode,
           s.principal::numeric(14,2)                       AS protected_principal,
           greatest(s.x, 0)::numeric(14,2)                  AS earned_working_capital,
           s.deployed::numeric(14,2)                        AS capital_deployed,
           s.realized::numeric(14,2)                        AS realized_profit,
           (s.principal + s.x - s.deployed)::numeric(14,2)  AS available_to_deploy,
           greatest(-s.x, 0)::numeric(14,2)                 AS principal_impairment,
           -- flags, not part of the schema's shape:
           s.x < 0                                          AS principal_impaired,
           (s.principal + s.x - s.deployed) < 0 OR -s.x > s.principal AS overdrawn,   -- violates the schema's invariants
           s.open_items,
           (SELECT count(*) FROM mbos.receipts r
             WHERE r.type = 'OUTCOME_RECORDED' AND r.actor->>'type' <> 'human'
               AND r.after_state->>'kind' IN (SELECT kind FROM mbos.capital_closing_kinds)) AS unconfirmed_closing_outcomes,
           s.as_of
    FROM s;

-- Exactly the fields of the schema's capital_ledger; validate with mbos.mission.ledger_errors.
CREATE FUNCTION mbos.capital_position_document(p_mode text DEFAULT 'dry_run') RETURNS jsonb
LANGUAGE sql STABLE AS $$
    SELECT jsonb_build_object('protected_principal', protected_principal, 'earned_working_capital', earned_working_capital,
                              'capital_deployed', capital_deployed, 'realized_profit', realized_profit,
                              'available_to_deploy', available_to_deploy, 'principal_impairment', principal_impairment,
                              'as_of', mbos.utc_iso(as_of))
    FROM mbos.v_capital_position WHERE mode = p_mode
$$;

-- ---------------------------------------------------------------------------
-- Replay: rebuild the entries from RECEIPTS ALONE with the same rule; capital_verify compares with the table.
-- ---------------------------------------------------------------------------
CREATE FUNCTION mbos.capital_replay()
RETURNS TABLE (receipt_seq bigint, receipt_id text, kind text, item_id text, amount numeric, basis numeric, net numeric)
LANGUAGE plpgsql STABLE AS $$
DECLARE r mbos.receipts; e jsonb; active boolean := false; principal numeric := 0; earned numeric := 0; deployed numeric := 0;
        dep jsonb := '{}'; closed jsonb := '{}'; avail numeric; idep numeric; iclosed boolean;
BEGIN
    FOR r IN SELECT * FROM mbos.receipts x
             WHERE x.type IN ('CONFIG_VERSION_BUMPED', 'BUDGET_COMMITTED', 'OUTCOME_RECORDED') ORDER BY x.seq LOOP
        avail := principal + earned - deployed;
        idep := coalesce((dep->>coalesce(r.item_id, ''))::numeric, 0);
        iclosed := coalesce((closed->>coalesce(r.item_id, ''))::boolean, false);
        e := mbos.capital_entry_for(r, active, avail, earned, idep, iclosed, false);
        CONTINUE WHEN e IS NULL;
        IF e->>'kind' = 'fund' THEN active := true; principal := principal + (e->>'amount')::numeric;
        ELSIF e->>'kind' = 'withdraw' THEN earned := earned - (e->>'amount')::numeric;
        ELSIF e->>'kind' = 'deploy' THEN
            deployed := deployed + (e->>'amount')::numeric;
            dep := jsonb_set(dep, ARRAY[e->>'item_id'], to_jsonb(idep + (e->>'amount')::numeric));
        ELSE
            deployed := deployed - (e->>'basis')::numeric; earned := earned + (e->>'net')::numeric;
            closed := jsonb_set(closed, ARRAY[e->>'item_id'], 'true'::jsonb);
        END IF;
        receipt_seq := r.seq; receipt_id := r.receipt_id; kind := e->>'kind'; item_id := e->>'item_id';
        amount := (e->>'amount')::numeric; basis := (e->>'basis')::numeric; net := (e->>'net')::numeric;
        RETURN NEXT;
    END LOOP;
END $$;

-- ok = the stored ledger equals the replay from receipts (same entries, same order, same numbers).
CREATE FUNCTION mbos.capital_verify() RETURNS TABLE (ok boolean, entries_checked bigint, problem text)
LANGUAGE plpgsql STABLE AS $$
DECLARE n bigint; mismatch text;
BEGIN
    SELECT count(*) INTO n FROM mbos.capital_ledger;
    SELECT format('entry for receipt %s differs or is missing/extra (stored: %s, replayed: %s)',
                  coalesce(s.source_receipt_id, p.receipt_id), s.kind, p.kind)
      INTO mismatch
      FROM (SELECT source_receipt_id, kind, item_id, amount, basis, net FROM mbos.capital_ledger) s
      FULL JOIN mbos.capital_replay() p ON p.receipt_id = s.source_receipt_id
      WHERE s.source_receipt_id IS NULL OR p.receipt_id IS NULL OR s.kind <> p.kind
         OR s.item_id IS DISTINCT FROM p.item_id OR s.amount <> p.amount
         OR s.basis IS DISTINCT FROM p.basis OR s.net IS DISTINCT FROM p.net
      LIMIT 1;
    RETURN QUERY SELECT mismatch IS NULL, n, mismatch;
END $$;

-- ---------------------------------------------------------------------------
-- Grants. Nobody gets INSERT on the ledger; the definer trigger writes it.
-- ---------------------------------------------------------------------------
REVOKE ALL ON mbos.mission, mbos.capital_ledger, mbos.capital_deploy_categories, mbos.capital_closing_kinds,
              mbos.v_mission_current, mbos.v_capital_position FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION mbos.mission_require_receipt(), mbos.set_mission(jsonb, jsonb, text, text[], text),
    mbos.capital_ledger_guard(),
    mbos.capital_entry_for(mbos.receipts, boolean, numeric, numeric, numeric, boolean, boolean), mbos.capital_state(text),
    mbos.receipts_to_capital(), mbos._capital_owner_receipt(text, numeric, jsonb, text, text[], text),
    mbos.capital_fund(numeric, jsonb, text, text[], text), mbos.capital_withdraw(numeric, jsonb, text, text[], text),
    mbos.capital_position_document(text), mbos.capital_replay(), mbos.capital_verify() FROM PUBLIC;
GRANT SELECT ON mbos.mission, mbos.capital_ledger, mbos.capital_deploy_categories, mbos.capital_closing_kinds,
                mbos.v_mission_current, mbos.v_capital_position
    TO agent_read, agent_write, gateway, approver, policy_admin;
GRANT EXECUTE ON FUNCTION mbos.capital_position_document(text), mbos.capital_replay(), mbos.capital_verify(),
    mbos.capital_state(text), mbos.capital_entry_for(mbos.receipts, boolean, numeric, numeric, numeric, boolean, boolean)
    TO agent_read, agent_write, gateway, approver, policy_admin;
-- The receipt triggers run in the writer's session: every role that appends receipts must be able to run the
-- (definer) derivation trigger function and the mission guard.
GRANT EXECUTE ON FUNCTION mbos.receipts_to_capital(), mbos.mission_require_receipt(), mbos.capital_ledger_guard()
    TO agent_write, gateway, approver, policy_admin, outbox_relay;
-- Owner channel only:
GRANT INSERT ON mbos.mission TO approver;
GRANT EXECUTE ON FUNCTION mbos.set_mission(jsonb, jsonb, text, text[], text), mbos._capital_owner_receipt(text, numeric, jsonb, text, text[], text),
    mbos.capital_fund(numeric, jsonb, text, text[], text), mbos.capital_withdraw(numeric, jsonb, text, text[], text) TO approver;
