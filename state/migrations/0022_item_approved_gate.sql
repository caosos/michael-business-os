-- 0022_item_approved_gate.sql — READY_QUEUE D-27 (found in D-26a): the item edge AWAITING_APPROVAL -> APPROVED was not gated.
--   Taking it now requires (1) a role of approver / gateway / mbos_owner (an agent_write-only login is refused, 42501) and
--   (2) an APPROVAL_DECIDED receipt with decision YES or MODIFY for an action request of THIS item, recorded after the item
--   last entered AWAITING_APPROVAL (so an approval from an earlier cycle cannot be reused). Refusal: MB005.
--   items_before_write is 0002 verbatim plus the gate block.

CREATE OR REPLACE FUNCTION mbos.items_before_write() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE entered bigint;
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
        IF NEW.state = 'APPROVED' AND OLD.state IS DISTINCT FROM 'APPROVED' THEN
            IF NOT (pg_has_role(current_user, 'approver', 'MEMBER') OR pg_has_role(current_user, 'gateway', 'MEMBER')
                    OR pg_has_role(current_user, 'mbos_owner', 'MEMBER')) THEN
                RAISE EXCEPTION 'mbos: role % may not move an item to APPROVED', current_user USING ERRCODE = '42501';
            END IF;
            SELECT max(seq) INTO entered FROM mbos.receipts
             WHERE type = 'ITEM_STATE_CHANGED' AND item_id = NEW.item_id AND after_state->>'state' = 'AWAITING_APPROVAL';
            IF NOT EXISTS (
                   SELECT 1 FROM mbos.receipts r
                   WHERE r.type = 'APPROVAL_DECIDED' AND r.item_id = NEW.item_id
                     AND r.after_state->>'decision' IN ('YES', 'MODIFY') AND r.seq > coalesce(entered, 0)) THEN
                RAISE EXCEPTION 'mbos: item % cannot be APPROVED without a YES/MODIFY approval receipt since it entered AWAITING_APPROVAL',
                    NEW.item_id USING ERRCODE = 'MB005';
            END IF;
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
