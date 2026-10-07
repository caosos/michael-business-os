-- 0006_r12_strict_item_edges.sql — READY_QUEUE D-05, coordinator ruling R12 (re-affirmed 2026-10-07).
-- The STRICT item state machine (frozen ADR-0004 text) is canonical:
--   * every item passes RESEARCHING (03's producer lives there)  -> drop NORMALIZED->SCORED
--   * a YES on a held request is re-presented first               -> drop HELD->APPROVED
--   * LEARNED is terminal                                         -> drop LEARNED->ARCHIVED / LEARNED->FAILED
-- Kept: ACTED->AWAITING_APPROVAL (follow-up action on the same item). Reverts the accommodation in 0005.
-- The migrator writes this migration's CONFIG_VERSION_BUMPED receipt in the same transaction.
DELETE FROM mbos.item_state_transitions
WHERE (from_state, to_state) IN (('NORMALIZED','SCORED'), ('HELD','APPROVED'),
                                 ('LEARNED','ARCHIVED'), ('LEARNED','FAILED'));
UPDATE mbos.item_states SET terminal = true WHERE state = 'LEARNED';
