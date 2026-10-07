-- 0012_deferred_approval_provenance.sql — D-13 review finding (Agent 01 spine_d.decide, MODIFY path).
-- A human decision's provenance may be written BEFORE its approval row in the same transaction (MODIFY:
-- provenance citing the new approval_id -> successor request -> MODIFY approval). The FK still holds, but is
-- checked at COMMIT: a provenance row can never commit pointing at an approval that does not exist.
ALTER TABLE mbos.provenance DROP CONSTRAINT provenance_approval_fk;
ALTER TABLE mbos.provenance ADD CONSTRAINT provenance_approval_fk
    FOREIGN KEY (approval_id) REFERENCES mbos.approvals (approval_id) DEFERRABLE INITIALLY DEFERRED;
