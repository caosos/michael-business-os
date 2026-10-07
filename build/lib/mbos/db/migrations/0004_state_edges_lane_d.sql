-- 0004: ruling R12 — the Item edge table is Agent 04's (lane D owns state; it follows ADR-0004 literally).
--   remove  NORMALIZED -> SCORED   (every item passes RESEARCHING: DISCOVER → NORMALIZE → RESEARCH → SCORE)
--   remove  HELD -> APPROVED       (a YES on a held request first re-presents it: HELD → AWAITING_APPROVAL → APPROVED)
--   remove  LEARNED -> ARCHIVED / FAILED (LEARNED is terminal in lane D)
--   add     ACTED -> AWAITING_APPROVAL (follow-up action on the same item, e.g. buy then list; ADR-0009 item 7)
DELETE FROM mbos.item_state_transitions WHERE (from_state, to_state) IN
    (('NORMALIZED', 'SCORED'), ('HELD', 'APPROVED'), ('LEARNED', 'ARCHIVED'), ('LEARNED', 'FAILED'));
INSERT INTO mbos.item_state_transitions (from_state, to_state) VALUES ('ACTED', 'AWAITING_APPROVAL');
