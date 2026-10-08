# Receipt: C-25 attested evidence, truthful status, WHY/TRANSPORT, plan legs + HOLD

Lane 03. DRY-RUN. No message sent, nothing spent, no contract changed. Provenance: audit findings F-90, F-93, F-94, F-99 from `docs/qa/OPERATOR_AUDIT.md` (Agent 07 G-20); queue row C-25 @ `origin/research/agent-01-coordinator`.

## What changed (`economics/`)
- **F-90** `inputs.py`: an `Item.research` entry with `field = "attestation:<key>"` (written by spine `record_attestation`, A-40) and a `provenance_id` sets that evidence flag in the engine input. Only person-confirmable keys count (flip: condition_verified, fault_identified, title_verified, demand_evidence, seller_screened, remote_verification; service: scope_verified, customer_screened, price_agreed_in_writing, materials_priced, access_and_schedule_confirmed, repeat_or_referral, remote_verification). Comp counts, price spread and skill fit stay computed. Basis UNKNOWN, a wrong-lane key or a missing provenance id is ignored. The flag flows through the existing evidence weights (confidence) and `inputs_hash`; the Item is not mutated.
  - Doorbell case (`smart_home_install` minus scope_verified/customer_screened): MAYBE, waiting on scope_verified, confidence 0.40 -> 0.70 with the scope attestation (YES) -> 0.85 with both.
- **F-93** `comps_feed.waiting_status` / `research_step(...)["status_text"]`: "Waiting for a price you saw ..." or "Last re-check failed: <reason>". Never "running".
- **F-99** `enrich._why_lines`: a flip whose transport mode is not definite now says "UNKNOWN ... no transport penalty is assumed" (was silent while the TRANSPORT block was UNKNOWN). `examples/deal_sniffer/concrete_saw.json` regenerated; that one added line is the whole diff.
- **F-94** `mission.plan_week`: every leg has `title`, `verdict`, `waiting_on` (from the scorecard's evidence search, never invented). A plan with no YES leg is `HOLD`; held legs report `cash_at_risk` 0 (Agent 01's `plan_errors` allows only DEPLOY to commit cash) and the leg `why` says what would be at risk if it became a YES.

## Interface for A-40 / F-29
Attestation research entry: `{"finding": <note>, "field": "attestation:<evidence_key>", "basis": "FACT", "provenance_id": "prov_..."}` where the provenance is human (owner channel).

## Verification
`cd economics && PYTHONPATH=src:tests python -m pytest tests -q` -> 368 passed, 22 skipped. With Agent 01's contracts and `mbos` on the path: 379 passed, 11 skipped (includes `plan_errors` on HOLD/DEPLOY plans). Scoring config and engine version unchanged (no number changes for Items without attestations).
