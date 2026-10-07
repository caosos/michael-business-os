-- 0004_views_grants.sql — contract-shaped read views, reporting views, least-privilege grants.
-- Group roles are created by state/bootstrap/roles.sql (cluster-level, run once as superuser).

-- ---------------------------------------------------------------------------
-- Contract documents (A10 conformance reads these)
-- ---------------------------------------------------------------------------
CREATE VIEW mbos.v_receipt_documents AS
    SELECT r.seq, r.receipt_id, mbos.receipt_document(r) AS doc FROM mbos.receipts r;

CREATE VIEW mbos.v_item_documents AS
    SELECT i.item_id, i.version, i.doc || jsonb_build_object(
        'action_request_ids', coalesce((SELECT jsonb_agg(a.action_request_id ORDER BY a.created_at)
                                        FROM mbos.action_requests a WHERE a.item_id = i.item_id), '[]'),
        'approval_ids',       coalesce((SELECT jsonb_agg(ap.approval_id ORDER BY ap.seq)
                                        FROM mbos.approvals ap JOIN mbos.action_requests a USING (action_request_id)
                                        WHERE a.item_id = i.item_id), '[]'),
        'receipt_ids',        coalesce((SELECT jsonb_agg(r.receipt_id ORDER BY r.seq)
                                        FROM mbos.receipts r WHERE r.item_id = i.item_id), '[]'),
        'outcome_ids',        coalesce((SELECT jsonb_agg(o.outcome_id ORDER BY o.seq)
                                        FROM mbos.outcomes o WHERE o.item_id = i.item_id), '[]')) AS doc
    FROM mbos.items i;

CREATE VIEW mbos.v_action_request_documents AS
    SELECT a.action_request_id, mbos.jsonb_strip_top_nulls(
        (to_jsonb(a) - ARRAY['updated_at','version'])
        || jsonb_build_object('created_at', mbos.utc_iso(a.created_at), 'expires_at', mbos.utc_iso(a.expires_at))) AS doc
    FROM mbos.action_requests a;

CREATE VIEW mbos.v_approval_documents AS
    SELECT ap.approval_id, mbos.jsonb_strip_top_nulls(
        (to_jsonb(ap) - 'seq')
        || jsonb_build_object('decided_at', mbos.utc_iso(ap.decided_at), 'expires_at', mbos.utc_iso(ap.expires_at))) AS doc
    FROM mbos.approvals ap;

CREATE VIEW mbos.v_provenance_documents AS
    SELECT p.provenance_id, mbos.jsonb_strip_top_nulls(
        (to_jsonb(p) - 'seq')
        || jsonb_build_object('created_at', mbos.utc_iso(p.created_at), 'fetched_at', mbos.utc_iso(p.fetched_at))) AS doc
    FROM mbos.provenance p;

CREATE VIEW mbos.v_outcome_documents AS
    SELECT o.outcome_id, mbos.jsonb_strip_top_nulls(
        (to_jsonb(o) - ARRAY['seq','recorded_at'])
        || jsonb_build_object('observed_at', mbos.utc_iso(o.observed_at))) AS doc
    FROM mbos.outcomes o;

-- ---------------------------------------------------------------------------
-- Governance / audit views
-- ---------------------------------------------------------------------------
-- Current policy: latest effective version per key. No row => the PDP must deny (default deny).
CREATE VIEW mbos.policy_current AS
    SELECT DISTINCT ON (policy_key) *
    FROM mbos.policy WHERE effective_from <= now()
    ORDER BY policy_key, version DESC;

-- A7 audit: must always be empty in wave one (also blocked by receipts_wave1_dry_run_only).
CREATE VIEW mbos.v_a7_live_effects AS
    SELECT seq, receipt_id, type, action_request_id, effector_response
    FROM mbos.receipts
    WHERE effector_response IS NOT NULL AND effector_response->'dry_run' IS DISTINCT FROM 'true'::jsonb;

CREATE VIEW mbos.v_budget_reservations AS
    SELECT r.entry_id AS reservation_id, r.ts, r.category, r.currency, r.action_request_id, r.amount AS reserved,
           coalesce(sum(s.amount) FILTER (WHERE s.kind = 'commit'), 0)  AS committed,
           coalesce(sum(s.amount) FILTER (WHERE s.kind = 'release'), 0) AS released,
           r.amount - coalesce(sum(s.amount), 0)                        AS outstanding
    FROM mbos.budget_ledger r
    LEFT JOIN mbos.budget_ledger s ON s.reservation_id = r.entry_id
    WHERE r.kind = 'reserve'
    GROUP BY r.entry_id;

-- ---------------------------------------------------------------------------
-- Reporting views (round-two gap list item 4)
-- ---------------------------------------------------------------------------
CREATE VIEW mbos.v_pipeline_by_lane AS
    SELECT type AS lane, state, count(*) AS items, max(updated_at) AS last_change
    FROM mbos.items GROUP BY type, state;

CREATE VIEW mbos.v_approval_latency AS
    SELECT ap.approval_id, ap.action_request_id, a.item_id, a.category, ap.decision,
           coalesce(req.ts, a.created_at) AS requested_at, ap.decided_at,
           ap.decided_at - coalesce(req.ts, a.created_at) AS latency
    FROM mbos.approvals ap
    JOIN mbos.action_requests a USING (action_request_id)
    LEFT JOIN LATERAL (SELECT min(r.ts) AS ts FROM mbos.receipts r
                       WHERE r.action_request_id = ap.action_request_id AND r.type = 'APPROVAL_REQUESTED') req ON true;

CREATE VIEW mbos.v_hold_backlog AS
    SELECT a.action_request_id, a.item_id, a.category, a.capability, a.expires_at,
           h.approval_id, h.decided_at AS held_at, h.hold,
           (h.hold->>'hold_until')::timestamptz AS hold_until,
           now() - h.decided_at AS held_for
    FROM mbos.action_requests a
    JOIN LATERAL (SELECT * FROM mbos.approvals ap WHERE ap.action_request_id = a.action_request_id
                  ORDER BY ap.seq DESC LIMIT 1) h ON h.decision = 'HOLD'
    WHERE a.status = 'held';

CREATE VIEW mbos.v_pnl_by_item AS
    SELECT i.item_id, i.type AS lane, i.category, i.state,
           sum((o.realized->>'revenue')::numeric)    AS revenue,
           sum((o.realized->>'total_cost')::numeric) AS total_cost,
           sum((o.realized->>'net_profit')::numeric) AS net_profit,
           sum((o.realized->>'hours')::numeric)      AS hours,
           count(o.outcome_id)                       AS outcomes
    FROM mbos.items i LEFT JOIN mbos.outcomes o USING (item_id)
    GROUP BY i.item_id;

-- ---------------------------------------------------------------------------
-- Grants. Nothing is granted to PUBLIC. UPDATE/DELETE/TRUNCATE on ledger tables are granted to nobody;
-- the append-only triggers additionally stop the owner.
-- ---------------------------------------------------------------------------
REVOKE ALL ON SCHEMA mbos FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA mbos FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA mbos FROM PUBLIC;

GRANT USAGE ON SCHEMA mbos TO agent_read, agent_write, gateway, approver, policy_admin, outbox_relay;
GRANT SELECT ON ALL TABLES IN SCHEMA mbos TO agent_read, agent_write, gateway, approver, policy_admin;

-- Pure helpers / read functions (also invoked by column defaults and triggers as the calling role).
GRANT EXECUTE ON FUNCTION
    mbos.ulid(), mbos.new_id(text), mbos.sha256_text(text), mbos.payload_hash(jsonb), mbos.utc_iso(timestamptz),
    mbos.jsonb_strip_top_nulls(jsonb), mbos.receipt_canonical(mbos.receipts), mbos.receipt_document(mbos.receipts),
    mbos.chain_head(), mbos.verify_chain(bigint, bigint, text), mbos.idempotent_receipt(text, text),
    mbos.require_receipt(text[], text, text, jsonb), mbos.budget_exposure(text, text),
    mbos.cjson(jsonb), mbos.cjson_number(jsonb), mbos.cjson_sha256(jsonb),          -- ADR-0010 (0000)
    mbos.rh1_hash_document(jsonb), mbos.rh1_row_hash(jsonb)
TO agent_read, agent_write, gateway, approver, policy_admin;

GRANT EXECUTE ON FUNCTION mbos.record_provenance(jsonb), mbos.append_receipt(jsonb)
TO agent_write, gateway, approver, policy_admin;
GRANT INSERT ON mbos.provenance, mbos.receipts TO agent_write, gateway, approver, policy_admin;

-- agent_write: State MCP server (the only agent write path). Items, proposals, outcomes, lessons.
GRANT INSERT ON mbos.items, mbos.action_requests, mbos.outcomes, mbos.lessons TO agent_write;
GRANT UPDATE (state, doc, category) ON mbos.items TO agent_write;
GRANT UPDATE (status) ON mbos.action_requests TO agent_write;   -- only for record_outcome's executed -> outcome_recorded
GRANT EXECUTE ON FUNCTION
    mbos.create_item(jsonb, jsonb, text, text[], text),
    mbos.transition_item(text, text, jsonb, text, text[], text, int, jsonb),
    mbos.update_item_doc(text, jsonb, text, jsonb, text, text[], text, int, jsonb),
    mbos.propose_action(jsonb, jsonb, text, text),
    mbos.record_outcome(jsonb, jsonb, text, text),
    mbos.record_lesson(jsonb, jsonb, text, text)
TO agent_write;

-- gateway: Action Gateway / execution guard (05). Classifies, executes, budgets. Cannot approve.
GRANT UPDATE (status, tier, policy_decision_ref) ON mbos.action_requests TO gateway;
GRANT UPDATE (state) ON mbos.items TO gateway;
GRANT INSERT ON mbos.budget_ledger TO gateway;
GRANT EXECUTE ON FUNCTION
    mbos.set_action_status(text, text, text, jsonb, text, text[], text, jsonb, int),
    mbos.transition_item(text, text, jsonb, text, text[], text, int, jsonb),
    mbos.budget_reserve(text, numeric, text, numeric, jsonb, text, text[], text),
    mbos.budget_settle(text, text, numeric, jsonb, text, text[], text)
TO gateway;

-- approver: Operator UI backend recording Michael's YES / NO / MODIFY / HOLD. Cannot execute or spend.
GRANT INSERT ON mbos.approvals, mbos.action_requests TO approver;   -- action_requests: MODIFY successor
GRANT UPDATE (status) ON mbos.action_requests TO approver;
GRANT UPDATE (state) ON mbos.items TO approver;
GRANT EXECUTE ON FUNCTION
    mbos.record_approval(jsonb, jsonb, text, text, text[]),
    mbos.propose_action(jsonb, jsonb, text, text),
    mbos.transition_item(text, text, jsonb, text, text[], text, int, jsonb)
TO approver;

-- policy_admin: governance changes (human-initiated). Policy rows only.
GRANT INSERT ON mbos.policy TO policy_admin;
GRANT EXECUTE ON FUNCTION mbos.publish_policy(jsonb, jsonb, text, text) TO policy_admin;

-- outbox_relay: delivery bookkeeping only; sees outbox, nothing else.
GRANT SELECT, UPDATE (dispatched_at, attempts, last_error, available_at) ON mbos.outbox TO outbox_relay;
GRANT EXECUTE ON FUNCTION mbos.outbox_claim(int), mbos.outbox_mark(text, boolean, text, interval) TO outbox_relay;
-- mbos.outbox_prune() stays owner-only (maintenance timer).
