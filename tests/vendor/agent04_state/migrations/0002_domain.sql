-- 0002_domain.sql — current-state + ledger tables and the same-transaction receipt invariant.
-- items / action_requests are current-state (mutable only through receipted transitions).
-- approvals / outcomes / lessons / policy / budget_ledger are append-only like receipts and provenance.
--
-- No workflow-resume / step-position tables here by design: DBOS owns workflow durability (ADR-0002).

-- ---------------------------------------------------------------------------
-- Same-transaction invariant. Deferred constraint triggers run at COMMIT and require a receipt written by
-- the SAME transaction (receipts.tx_id = pg_current_xact_id()). A state change without its receipt cannot
-- commit; a rolled-back transaction loses both. => "both or neither" (A1).
-- ---------------------------------------------------------------------------
CREATE FUNCTION mbos.require_receipt(p_types text[], p_column text, p_value text, p_after jsonb DEFAULT NULL)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE found boolean;
BEGIN
    EXECUTE format(
        'SELECT EXISTS (SELECT 1 FROM mbos.receipts WHERE tx_id = pg_current_xact_id()
                          AND type = ANY ($1) AND %I = $2 AND ($3 IS NULL OR after_state @> $3))', p_column)
        INTO found USING p_types, p_value, p_after;
    IF NOT found THEN
        RAISE EXCEPTION 'mbos: no receipt for % % = % in this transaction (no action without a receipt)',
            p_types, p_column, p_value
            USING ERRCODE = 'MB003', HINT = 'Use the mbos.* API functions, which write the receipt atomically.';
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- Items (contract: item.schema.json). Columns hold the indexed/enforced fields; `doc` holds the rest of
-- the Item v1 document. Reference arrays (receipt_ids, action_request_ids, ...) are derived from the
-- ledger in v_item_documents, never stored, so they cannot drift.
-- ---------------------------------------------------------------------------
CREATE TABLE mbos.item_states (state text PRIMARY KEY, terminal boolean NOT NULL DEFAULT false);
INSERT INTO mbos.item_states VALUES
    ('DISCOVERED',false),('NORMALIZED',false),('RESEARCHING',false),('SCORED',false),('RECOMMENDED',false),
    ('AWAITING_APPROVAL',false),('HELD',false),('APPROVED',false),('REJECTED',false),('ACTING',false),
    ('ACTED',false),('OUTCOME_RECORDED',false),('LEARNED',true),('ARCHIVED',true),('FAILED',true);

-- Item flow (integration plan §4). ARCHIVED and FAILED are reachable from any non-terminal state.
-- Edges marked (*) are Agent 04 interpretations, flagged for Agent 01 review in AGENT_STATUS.md.
CREATE TABLE mbos.item_state_transitions (
    from_state text NOT NULL REFERENCES mbos.item_states,
    to_state   text NOT NULL REFERENCES mbos.item_states,
    note       text,
    PRIMARY KEY (from_state, to_state)
);
INSERT INTO mbos.item_state_transitions VALUES
    ('DISCOVERED','NORMALIZED',NULL),
    ('NORMALIZED','RESEARCHING',NULL),
    ('RESEARCHING','SCORED',NULL),
    ('SCORED','RESEARCHING',NULL),
    ('SCORED','RECOMMENDED',NULL),
    ('RECOMMENDED','RESEARCHING','MAYBE: back to cheapest decisive evidence (ADR-0004 routing)'),
    ('RECOMMENDED','AWAITING_APPROVAL','YES: action request(s) created'),
    ('AWAITING_APPROVAL','APPROVED',NULL),
    ('AWAITING_APPROVAL','HELD',NULL),
    ('AWAITING_APPROVAL','REJECTED',NULL),
    ('HELD','AWAITING_APPROVAL','(*) wake / re-present; HOLD never auto-executes'),
    ('HELD','REJECTED','(*)'),
    ('APPROVED','ACTING',NULL),
    ('ACTING','ACTED',NULL),
    ('ACTED','OUTCOME_RECORDED',NULL),
    ('ACTED','AWAITING_APPROVAL','(*) follow-up action on the same item, e.g. buy then list'),
    ('OUTCOME_RECORDED','LEARNED',NULL);
INSERT INTO mbos.item_state_transitions
    SELECT s.state, t.to_state, 'any non-terminal state' FROM mbos.item_states s
    CROSS JOIN (VALUES ('ARCHIVED'),('FAILED')) AS t(to_state)
    WHERE NOT s.terminal;

CREATE TABLE mbos.items (
    item_id        text PRIMARY KEY DEFAULT mbos.new_id('itm') CHECK (item_id ~ '^itm_[0-9A-HJKMNP-TV-Z]{26}$'),
    schema_version text NOT NULL DEFAULT '1.0.0' CHECK (schema_version = '1.0.0'),
    type           text NOT NULL CHECK (type IN ('flip','service')),
    category       text NOT NULL,
    state          text NOT NULL DEFAULT 'DISCOVERED' REFERENCES mbos.item_states,
    dedup_key      text NOT NULL UNIQUE,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    version        int NOT NULL DEFAULT 1 CHECK (version >= 1),   -- optimistic locking
    doc            jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    CONSTRAINT items_category_per_type CHECK (
        (type = 'flip' AND category IN ('trailer','mower','generator','welder','compressor','tool',
            'commercial_equipment','mechanical_equipment','project_vehicle','other_asset'))
     OR (type = 'service' AND category IN ('mobile_repair','equipment_repair','drywall_repair','assembly',
            'handyman','smart_home_install','technical_service','mechanical_service','other_service')))
);
CREATE INDEX items_lane_state_idx ON mbos.items (type, state);

CREATE FUNCTION mbos.items_before_write() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF (NEW.item_id, NEW.type, NEW.created_at, NEW.dedup_key) IS DISTINCT FROM
           (OLD.item_id, OLD.type, OLD.created_at, OLD.dedup_key) THEN
            RAISE EXCEPTION 'mbos: item_id, type, created_at and dedup_key are immutable' USING ERRCODE = 'MB001';
        END IF;
        IF NEW.state <> OLD.state AND NOT EXISTS (
               SELECT 1 FROM mbos.item_state_transitions WHERE from_state = OLD.state AND to_state = NEW.state) THEN
            RAISE EXCEPTION 'mbos: illegal item transition % -> %', OLD.state, NEW.state USING ERRCODE = 'MB004';
        END IF;
        NEW.version    := OLD.version + 1;
        NEW.updated_at := now();
    END IF;
    -- Columns are authoritative; the stored doc never carries derived reference arrays.
    NEW.doc := (NEW.doc - ARRAY['action_request_ids','approval_ids','receipt_ids','outcome_ids'])
        || jsonb_build_object('item_id', NEW.item_id, 'schema_version', NEW.schema_version, 'type', NEW.type,
                              'category', NEW.category, 'state', NEW.state, 'dedup_key', NEW.dedup_key,
                              'created_at', mbos.utc_iso(NEW.created_at), 'updated_at', mbos.utc_iso(NEW.updated_at));
    RETURN NEW;
END $$;
CREATE TRIGGER aa_items_before_write BEFORE INSERT OR UPDATE ON mbos.items
    FOR EACH ROW EXECUTE FUNCTION mbos.items_before_write();
CREATE TRIGGER zz_items_no_delete BEFORE DELETE ON mbos.items
    FOR EACH ROW EXECUTE FUNCTION mbos.reject_mutation();   -- retire with ARCHIVED, never delete
CREATE TRIGGER zz_items_no_truncate BEFORE TRUNCATE ON mbos.items
    FOR EACH STATEMENT EXECUTE FUNCTION mbos.reject_mutation();

CREATE FUNCTION mbos.items_require_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' OR NEW.state IS DISTINCT FROM OLD.state THEN
        PERFORM mbos.require_receipt(ARRAY['ITEM_STATE_CHANGED'], 'item_id', NEW.item_id,
                                     jsonb_build_object('state', NEW.state));
    ELSE
        PERFORM mbos.require_receipt(ARRAY['ITEM_STATE_CHANGED','SCORE_RECORDED','RECOMMENDATION_RECORDED'],
                                     'item_id', NEW.item_id);
    END IF;
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER zz_items_receipt AFTER INSERT OR UPDATE ON mbos.items
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION mbos.items_require_receipt();

-- ---------------------------------------------------------------------------
-- Action requests (contract: action-request.schema.json). Payload is hash-frozen at insert; only status
-- (and the policy decision ref) moves, and every move is receipted.
-- ---------------------------------------------------------------------------
-- allowed_roles: which group role may make the move (least privilege on top of column grants).
-- Members of mbos_owner (migrations/maintenance) and superusers may make any legal move.
CREATE TABLE mbos.action_request_transitions (
    from_status   text NOT NULL,
    to_status     text NOT NULL,
    allowed_roles text[] NOT NULL,
    PRIMARY KEY (from_status, to_status)
);
INSERT INTO mbos.action_request_transitions VALUES
    ('drafted','classified',           '{gateway}'),
    ('classified','pending_approval',  '{gateway}'),
    ('classified','auto_approved',     '{gateway}'),   -- tier >= 1 only (constraint below)
    ('classified','rejected',          '{gateway}'),   -- policy deny
    ('pending_approval','approved',    '{approver}'),
    ('pending_approval','rejected',    '{approver}'),  -- NO, or MODIFY (closed; successor has derived_from)
    ('pending_approval','held',        '{approver}'),
    ('pending_approval','expired',     '{gateway}'),
    ('held','pending_approval',        '{gateway,approver}'),  -- wake / re-present
    ('held','approved',                '{approver}'),
    ('held','rejected',                '{approver}'),
    ('held','held',                    '{approver}'),  -- a new HOLD decision on a held request
    ('held','expired',                 '{gateway}'),
    ('approved','executing',           '{gateway}'),
    ('auto_approved','executing',      '{gateway}'),
    ('executing','executed',           '{gateway}'),
    ('executing','failed',             '{gateway}'),
    ('executed','outcome_recorded',    '{agent_write,gateway}');
INSERT INTO mbos.action_request_transitions
    SELECT s, 'cancelled_by_freeze', '{gateway}'
    FROM unnest(ARRAY['drafted','classified','pending_approval','held','approved','auto_approved']) s;

CREATE TABLE mbos.action_requests (
    action_request_id        text PRIMARY KEY DEFAULT mbos.new_id('areq') CHECK (action_request_id ~ '^areq_[0-9A-HJKMNP-TV-Z]{26}$'),
    item_id                  text NOT NULL REFERENCES mbos.items,
    recommendation_id        text CHECK (recommendation_id ~ '^rec_[0-9A-HJKMNP-TV-Z]{26}$'),
    derived_from             text REFERENCES mbos.action_requests,
    created_at               timestamptz NOT NULL DEFAULT now(),
    proposed_by              text NOT NULL,
    on_behalf_of             text NOT NULL DEFAULT 'michael' CHECK (on_behalf_of = 'michael'),
    capability               text NOT NULL,
    category                 text NOT NULL CHECK (category IN ('message','offer','money','purchase','publishing',
                                 'scheduling','price_change','phone_call','sms','email','external_commitment')),
    payload                  jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    payload_hash             text NOT NULL CHECK (payload_hash ~ '^sha256:[0-9a-f]{64}$'),
    idempotency_key          text NOT NULL UNIQUE,
    estimated_cost           jsonb CHECK (estimated_cost IS NULL OR (estimated_cost ? 'amount' AND estimated_cost ? 'currency')),
    max_cost                 jsonb CHECK (max_cost IS NULL OR (max_cost ? 'amount' AND max_cost ? 'currency')),
    reversibility            text NOT NULL CHECK (reversibility IN ('reversible','partially_reversible','irreversible')),
    untrusted_inputs_present boolean,
    tier                     int NOT NULL DEFAULT 0 CHECK (tier IN (0,1,2,3)),
    policy_decision_ref      text,
    score_ref                text CHECK (score_ref ~ '^scr_[0-9A-HJKMNP-TV-Z]{26}$'),
    status                   text NOT NULL DEFAULT 'drafted' CHECK (status IN ('drafted','classified','pending_approval',
                                 'held','approved','auto_approved','rejected','expired','executing','executed',
                                 'failed','outcome_recorded','cancelled_by_freeze')),
    expires_at               timestamptz NOT NULL,
    provenance_ids           text[] NOT NULL CHECK (cardinality(provenance_ids) >= 1),
    target                   jsonb CHECK (target IS NULL OR jsonb_typeof(target) = 'object'),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    version                  int NOT NULL DEFAULT 1,
    -- Contract allOf: these always force tier 0 (05 + MICHAEL_DECISIONS #5).
    CONSTRAINT areq_irreversible_tier0 CHECK (reversibility <> 'irreversible' OR tier = 0),
    CONSTRAINT areq_untrusted_tier0    CHECK (untrusted_inputs_present IS NOT TRUE OR tier = 0),
    CONSTRAINT areq_money_tier0        CHECK (category NOT IN ('money','purchase','external_commitment') OR tier = 0),
    CONSTRAINT areq_auto_needs_tier    CHECK (status <> 'auto_approved' OR tier >= 1),
    CONSTRAINT areq_not_self_derived   CHECK (derived_from IS DISTINCT FROM action_request_id)
);
CREATE INDEX areq_item_idx   ON mbos.action_requests (item_id);
CREATE INDEX areq_status_idx ON mbos.action_requests (status);

CREATE FUNCTION mbos.areq_before_write() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE missing text[];
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'drafted' THEN
            RAISE EXCEPTION 'mbos: action requests are created as drafted' USING ERRCODE = 'MB004';
        END IF;
        SELECT array_agg(p) INTO missing FROM unnest(NEW.provenance_ids) p
        WHERE NOT EXISTS (SELECT 1 FROM mbos.provenance v WHERE v.provenance_id = p);
        IF missing IS NOT NULL THEN
            RAISE EXCEPTION 'mbos: action request references unknown provenance ids %', missing USING ERRCODE = 'MB002';
        END IF;
        RETURN NEW;
    END IF;
    -- UPDATE: everything except status / policy_decision_ref is frozen (payload re-checked by the guard).
    -- The PDP may set the tier only while classifying (drafted -> classified).
    IF (to_jsonb(NEW) - ARRAY['status','policy_decision_ref','updated_at','version','tier'])
       IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['status','policy_decision_ref','updated_at','version','tier'])
       OR (NEW.tier <> OLD.tier AND NOT (OLD.status = 'drafted' AND NEW.status = 'classified')) THEN
        RAISE EXCEPTION 'mbos: action request % is frozen; MODIFY creates a new request with derived_from',
            OLD.action_request_id USING ERRCODE = 'MB001';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status OR (OLD.status = 'held' AND NEW.status = 'held') THEN
        IF NOT EXISTS (SELECT 1 FROM mbos.action_request_transitions t
                       WHERE t.from_status = OLD.status AND t.to_status = NEW.status) THEN
            RAISE EXCEPTION 'mbos: illegal action request transition % -> %', OLD.status, NEW.status USING ERRCODE = 'MB004';
        END IF;
        IF NOT pg_has_role(current_user, 'mbos_owner', 'MEMBER')
           AND NOT EXISTS (SELECT 1 FROM mbos.action_request_transitions t, unnest(t.allowed_roles) role
                       WHERE t.from_status = OLD.status AND t.to_status = NEW.status
                         AND pg_has_role(current_user, role, 'MEMBER')) THEN
            RAISE EXCEPTION 'mbos: role % may not move an action request % -> %', current_user, OLD.status, NEW.status
                USING ERRCODE = '42501';
        END IF;
    END IF;
    -- Defense in depth behind 05's execution guard: approved/executing needs a live YES on this exact payload.
    IF NEW.status IS DISTINCT FROM OLD.status AND (NEW.status = 'approved' OR (NEW.status = 'executing' AND OLD.status = 'approved'))
       AND NOT EXISTS (
           SELECT 1 FROM mbos.approvals ap
           WHERE ap.action_request_id = NEW.action_request_id AND ap.decision = 'YES'
             AND ap.payload_hash_seen = NEW.payload_hash
             AND (ap.expires_at IS NULL OR ap.expires_at > now())
             AND ap.seq = (SELECT max(seq) FROM mbos.approvals WHERE action_request_id = NEW.action_request_id)) THEN
        RAISE EXCEPTION 'mbos: % requires a current, unexpired YES approval for payload %', NEW.status, NEW.payload_hash
            USING ERRCODE = 'MB005';
    END IF;
    NEW.version := OLD.version + 1;
    NEW.updated_at := now();
    RETURN NEW;
END $$;
CREATE TRIGGER aa_areq_before_write BEFORE INSERT OR UPDATE ON mbos.action_requests
    FOR EACH ROW EXECUTE FUNCTION mbos.areq_before_write();
CREATE TRIGGER zz_areq_no_delete BEFORE DELETE ON mbos.action_requests
    FOR EACH ROW EXECUTE FUNCTION mbos.reject_mutation();
CREATE TRIGGER zz_areq_no_truncate BEFORE TRUNCATE ON mbos.action_requests
    FOR EACH STATEMENT EXECUTE FUNCTION mbos.reject_mutation();

CREATE FUNCTION mbos.areq_require_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM mbos.require_receipt(ARRAY['ACTION_PROPOSED'], 'action_request_id', NEW.action_request_id);
    ELSIF NEW.status IS DISTINCT FROM OLD.status OR NEW.policy_decision_ref IS DISTINCT FROM OLD.policy_decision_ref THEN
        PERFORM mbos.require_receipt(
            ARRAY['POLICY_DECIDED','APPROVAL_REQUESTED','APPROVAL_DECIDED','ACTION_EXECUTING','ACTION_EXECUTED',
                  'ACTION_FAILED','OUTCOME_RECORDED','KILL_SWITCH_CHANGED'],
            'action_request_id', NEW.action_request_id, jsonb_build_object('status', NEW.status));
    END IF;
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER zz_areq_receipt AFTER INSERT OR UPDATE ON mbos.action_requests
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION mbos.areq_require_receipt();

-- ---------------------------------------------------------------------------
-- Approvals (contract: approval.schema.json) — append-only; a new decision is a new row.
-- ---------------------------------------------------------------------------
CREATE TABLE mbos.approvals (
    approval_id       text PRIMARY KEY DEFAULT mbos.new_id('appr') CHECK (approval_id ~ '^appr_[0-9A-HJKMNP-TV-Z]{26}$'),
    seq               bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    action_request_id text NOT NULL REFERENCES mbos.action_requests,
    decision          text NOT NULL CHECK (decision IN ('YES','NO','MODIFY','HOLD')),
    decider           text NOT NULL,
    decided_at        timestamptz NOT NULL DEFAULT now(),
    channel           text NOT NULL CHECK (channel IN ('telegram','web','sms_reply','email_reply','cli')),
    auth_context      jsonb CHECK (auth_context IS NULL OR jsonb_typeof(auth_context) = 'object'),
    payload_hash_seen text NOT NULL CHECK (payload_hash_seen ~ '^sha256:[0-9a-f]{64}$'),
    modifications     jsonb,
    hold              jsonb,
    reason            text,
    scope             text NOT NULL CHECK (scope IN ('once','session','standing_rule')),
    expires_at        timestamptz,
    CONSTRAINT appr_modify_fields CHECK (decision <> 'MODIFY' OR (modifications ? 'new_action_request_id' AND modifications ? 'new_payload_hash')),
    CONSTRAINT appr_hold_fields   CHECK (decision <> 'HOLD' OR (jsonb_typeof(hold) = 'object' AND (hold ? 'hold_until' OR hold ? 'wake_on'))),
    CONSTRAINT appr_no_reason     CHECK (decision <> 'NO' OR coalesce(reason, '') <> ''),
    CONSTRAINT appr_standing_rule_step_up CHECK (scope <> 'standing_rule' OR auth_context->'step_up' = 'true'::jsonb)
);
CREATE INDEX approvals_areq_idx ON mbos.approvals (action_request_id);
ALTER TABLE mbos.provenance ADD CONSTRAINT provenance_approval_fk
    FOREIGN KEY (approval_id) REFERENCES mbos.approvals (approval_id);

CREATE FUNCTION mbos.approvals_before_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE a mbos.action_requests;
DECLARE successor mbos.action_requests;
BEGIN
    SELECT * INTO a FROM mbos.action_requests WHERE action_request_id = NEW.action_request_id FOR UPDATE;
    IF a.status NOT IN ('pending_approval','held') THEN
        RAISE EXCEPTION 'mbos: action request % is %, not awaiting a decision', a.action_request_id, a.status
            USING ERRCODE = 'MB004';
    END IF;
    IF NEW.payload_hash_seen <> a.payload_hash THEN
        RAISE EXCEPTION 'mbos: approval void — payload_hash_seen does not match the frozen payload'
            USING ERRCODE = 'MB005';
    END IF;
    IF NEW.decision IN ('YES','MODIFY') AND a.expires_at <= now() THEN
        RAISE EXCEPTION 'mbos: action request % expired at %', a.action_request_id, a.expires_at USING ERRCODE = 'MB005';
    END IF;
    IF NEW.decision = 'YES' AND (a.category IN ('money','purchase') OR a.reversibility = 'irreversible')
       AND NEW.auth_context->'step_up' IS DISTINCT FROM 'true'::jsonb THEN
        RAISE EXCEPTION 'mbos: money / irreversible approvals require step_up' USING ERRCODE = 'MB005';
    END IF;
    IF NEW.decision = 'MODIFY' THEN
        SELECT * INTO successor FROM mbos.action_requests
        WHERE action_request_id = NEW.modifications->>'new_action_request_id';
        IF successor.action_request_id IS NULL OR successor.derived_from IS DISTINCT FROM a.action_request_id
           OR successor.payload_hash <> NEW.modifications->>'new_payload_hash' THEN
            RAISE EXCEPTION 'mbos: MODIFY must reference a new request derived_from % with matching new_payload_hash',
                a.action_request_id USING ERRCODE = 'MB005';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER aa_approvals_before_insert BEFORE INSERT ON mbos.approvals
    FOR EACH ROW EXECUTE FUNCTION mbos.approvals_before_insert();
SELECT mbos.make_append_only('mbos.approvals');

CREATE FUNCTION mbos.approvals_require_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM mbos.require_receipt(ARRAY['APPROVAL_DECIDED'], 'approval_id', NEW.approval_id);
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER zz_approvals_receipt AFTER INSERT ON mbos.approvals
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION mbos.approvals_require_receipt();

-- Receipt FKs (added now that the referenced tables exist).
ALTER TABLE mbos.receipts
    ADD CONSTRAINT receipts_item_fk     FOREIGN KEY (item_id) REFERENCES mbos.items,
    ADD CONSTRAINT receipts_areq_fk     FOREIGN KEY (action_request_id) REFERENCES mbos.action_requests,
    ADD CONSTRAINT receipts_approval_fk FOREIGN KEY (approval_id) REFERENCES mbos.approvals;

-- ---------------------------------------------------------------------------
-- Outcomes (contract: outcome.schema.json) — append-only; never edits past scores.
-- ---------------------------------------------------------------------------
CREATE TABLE mbos.outcomes (
    outcome_id          text PRIMARY KEY DEFAULT mbos.new_id('outc') CHECK (outcome_id ~ '^outc_[0-9A-HJKMNP-TV-Z]{26}$'),
    seq                 bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    item_id             text NOT NULL REFERENCES mbos.items,
    action_request_id   text REFERENCES mbos.action_requests,
    scorecard_id        text CHECK (scorecard_id ~ '^scr_[0-9A-HJKMNP-TV-Z]{26}$'),
    observed_at         timestamptz NOT NULL,
    kind                text NOT NULL CHECK (kind IN ('flip_acquired','flip_sold','flip_unsold_salvaged',
                            'flip_repair_failed','flip_passed_missed','service_won','service_lost',
                            'service_completed','service_rework','service_paid','wasted_trip',
                            'message_replied','message_no_reply','lead_attributed')),
    predicted_vs_actual jsonb CHECK (predicted_vs_actual IS NULL OR jsonb_typeof(predicted_vs_actual) = 'array'),
    realized            jsonb CHECK (realized IS NULL OR jsonb_typeof(realized) = 'object'),
    attribution         jsonb CHECK (attribution IS NULL OR jsonb_typeof(attribution) = 'object'),
    notes               text,
    provenance_ids      text[] NOT NULL CHECK (cardinality(provenance_ids) >= 1),
    recorded_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX outcomes_item_idx ON mbos.outcomes (item_id);
ALTER TABLE mbos.receipts ADD CONSTRAINT receipts_outcome_fk FOREIGN KEY (outcome_id) REFERENCES mbos.outcomes;
SELECT mbos.make_append_only('mbos.outcomes');

CREATE FUNCTION mbos.outcomes_require_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM mbos.require_receipt(ARRAY['OUTCOME_RECORDED'], 'outcome_id', NEW.outcome_id);
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER zz_outcomes_receipt AFTER INSERT ON mbos.outcomes
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION mbos.outcomes_require_receipt();

-- ---------------------------------------------------------------------------
-- Lessons (ADR-0004 mapping: "a separate lessons table (04) emitting LESSON_RECORDED receipts").
-- Not a frozen contract yet; shape proposed by 04, consumer is 03 LEARN. Prefix lsn_ (flagged for 01).
-- ---------------------------------------------------------------------------
CREATE TABLE mbos.lessons (
    lesson_id              text PRIMARY KEY DEFAULT mbos.new_id('lsn') CHECK (lesson_id ~ '^lsn_[0-9A-HJKMNP-TV-Z]{26}$'),
    seq                    bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    created_at             timestamptz NOT NULL DEFAULT now(),
    scope                  text NOT NULL,   -- e.g. scoring, source, comms, marketing, ops
    statement              text NOT NULL CHECK (length(statement) > 0),
    basis                  text NOT NULL CHECK (basis IN ('FACT','INFERENCE','RECOMMENDATION','UNKNOWN')),
    item_id                text REFERENCES mbos.items,
    outcome_ids            text[],
    evidence               jsonb,
    proposed_config_change jsonb,           -- 03 config bump proposal; applying it needs an approval
    supersedes             text REFERENCES mbos.lessons,
    provenance_ids         text[] NOT NULL CHECK (cardinality(provenance_ids) >= 1)
);
SELECT mbos.make_append_only('mbos.lessons');

CREATE FUNCTION mbos.lessons_require_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM mbos.require_receipt(ARRAY['LESSON_RECORDED'], 'entity_id', NEW.lesson_id);
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER zz_lessons_receipt AFTER INSERT ON mbos.lessons
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION mbos.lessons_require_receipt();

-- ---------------------------------------------------------------------------
-- Policy (PDP data, ADR-0005; content owned by Agent 05). Versioned, append-only: a change is a new
-- version row. Default is deny: an action with no matching current row must be denied by the PDP.
-- ---------------------------------------------------------------------------
CREATE TABLE mbos.policy (
    policy_id      text PRIMARY KEY DEFAULT mbos.new_id('pol') CHECK (policy_id ~ '^pol_[0-9A-HJKMNP-TV-Z]{26}$'),
    policy_key     text NOT NULL,           -- e.g. 'category:money', 'capability:comms.sms.send', 'budget:purchase'
    version        int  NOT NULL CHECK (version >= 1),
    category       text,
    capability     text,
    tier           int CHECK (tier IN (0,1,2,3)),
    decision       text NOT NULL CHECK (decision IN ('deny','require_approval','allow')),
    limits         jsonb NOT NULL DEFAULT '{}'::jsonb,
    effective_from timestamptz NOT NULL DEFAULT now(),
    created_at     timestamptz NOT NULL DEFAULT now(),
    created_by     text NOT NULL,
    reason         text NOT NULL,
    provenance_ids text[] NOT NULL CHECK (cardinality(provenance_ids) >= 1),
    UNIQUE (policy_key, version),
    CONSTRAINT policy_money_gated CHECK (category NOT IN ('money','purchase','external_commitment') OR decision <> 'allow')
);
SELECT mbos.make_append_only('mbos.policy');

CREATE FUNCTION mbos.policy_before_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE cur int;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('mbos.policy:' || NEW.policy_key, 0));
    SELECT max(version) INTO cur FROM mbos.policy WHERE policy_key = NEW.policy_key;
    IF NEW.version <> coalesce(cur, 0) + 1 THEN
        RAISE EXCEPTION 'mbos: policy % next version must be %', NEW.policy_key, coalesce(cur, 0) + 1 USING ERRCODE = 'MB004';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER aa_policy_before_insert BEFORE INSERT ON mbos.policy
    FOR EACH ROW EXECUTE FUNCTION mbos.policy_before_insert();

CREATE FUNCTION mbos.policy_require_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM mbos.require_receipt(ARRAY['CONFIG_VERSION_BUMPED'], 'entity_id', NEW.policy_id);
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER zz_policy_receipt AFTER INSERT ON mbos.policy
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION mbos.policy_require_receipt();

-- ---------------------------------------------------------------------------
-- Budget ledger (real-world spend, 05: reserve -> commit | release; fail-closed). Append-only.
-- LLM spend is LiteLLM's ledger, not this one (C10: two ledgers).
-- ---------------------------------------------------------------------------
CREATE TABLE mbos.budget_ledger (
    entry_id          text PRIMARY KEY DEFAULT mbos.new_id('bud') CHECK (entry_id ~ '^bud_[0-9A-HJKMNP-TV-Z]{26}$'),
    seq               bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    ts                timestamptz NOT NULL DEFAULT now(),
    kind              text NOT NULL CHECK (kind IN ('reserve','commit','release')),
    category          text NOT NULL,
    action_request_id text NOT NULL REFERENCES mbos.action_requests,
    reservation_id    text REFERENCES mbos.budget_ledger (entry_id),
    amount            numeric(14,2) NOT NULL CHECK (amount > 0),
    currency          text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    cap_applied       numeric(14,2),
    provenance_ids    text[] NOT NULL CHECK (cardinality(provenance_ids) >= 1),
    CONSTRAINT budget_reservation_ref CHECK ((kind = 'reserve') = (reservation_id IS NULL))
);
CREATE INDEX budget_category_idx ON mbos.budget_ledger (category, currency);
SELECT mbos.make_append_only('mbos.budget_ledger');

CREATE FUNCTION mbos.budget_before_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE res mbos.budget_ledger; settled numeric;
BEGIN
    IF NEW.kind = 'reserve' THEN RETURN NEW; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('mbos.budget.res:' || NEW.reservation_id, 0));
    SELECT * INTO res FROM mbos.budget_ledger WHERE entry_id = NEW.reservation_id;
    IF res.kind IS DISTINCT FROM 'reserve' OR res.action_request_id <> NEW.action_request_id
       OR res.category <> NEW.category OR res.currency <> NEW.currency THEN
        RAISE EXCEPTION 'mbos: % must reference a matching reservation', NEW.kind USING ERRCODE = 'MB006';
    END IF;
    SELECT coalesce(sum(amount), 0) INTO settled FROM mbos.budget_ledger WHERE reservation_id = res.entry_id;
    IF settled + NEW.amount > res.amount THEN
        RAISE EXCEPTION 'mbos: % of % exceeds remaining reservation % (reserved %, settled %)',
            NEW.kind, NEW.amount, res.entry_id, res.amount, settled USING ERRCODE = 'MB006';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER aa_budget_before_insert BEFORE INSERT ON mbos.budget_ledger
    FOR EACH ROW EXECUTE FUNCTION mbos.budget_before_insert();

CREATE FUNCTION mbos.budget_require_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM mbos.require_receipt(ARRAY['BUDGET_' || CASE NEW.kind WHEN 'reserve' THEN 'RESERVED'
                                         WHEN 'commit' THEN 'COMMITTED' ELSE 'RELEASED' END],
                                 'entity_id', NEW.entry_id);
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER zz_budget_receipt AFTER INSERT ON mbos.budget_ledger
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION mbos.budget_require_receipt();
