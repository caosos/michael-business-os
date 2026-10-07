# Receipt: G-06, release-candidate re-run after E-13 (Agent 07, lane G)

- **Task:** G-06 (P0). **Claimed** `4cbfd07`. **Delivered** `e7434f4`. DRY-RUN only.
- **Verdict (FACT): NOT READY — one red case, and it fails safe.** 103 passed, 1 failed, 3 not applicable; 107 cases. The failing set was identical across two runs. The reference configuration is 104/104. Report: `docs/qa/RELEASE_CANDIDATE.md`.
- **Stack under test** (pins in `qa/impl_lane_pins.json`, all from `git archive`):
  - Agent 01 `mbos` `f8407c9`, `state_backend=lane_d`, `gateway_mode=lane_e`
  - Agent 04 `92d52b1` (D-16)
  - Agent 05 `e6afc28` (E-13), plus its whole `policy/` directory
  - PostgreSQL 16 + DBOS
  - The branch tips are status-only commits after those heads.

## What closed, verified on this stack (not taken from the peer's word)
- **F-24:** A9 8/8, including the replay regression. A denied approval can no longer fire after the switch is released.
- **F-25 / R22:** A5 5/5. No duplicate effect. A send that happened settles `executed`/ACTED. A crash before the send settles failed + RECONCILED.
- **F-22:** a publishing draft is proposed, approved (with step-up) and executed once in dry-run.
- **F-23:** regression test with an ungranted capability: the request is `rejected` and the item is not left awaiting Michael.

## What is still red
- **F-40 (owner 01 + 05).**
  - Publishing needs Michael's step-up under lane E's policy (`GATED:publishing:tier0; step_up=required`).
  - The spine's `decide` accepts a YES without it, and the gateway then refuses (`STEP_UP_REQUIRED`, `AUTH_CONTEXT_REQUIRED`). The item ends FAILED and Michael's approval is lost.
  - Nothing executes; with step-up it executes once.
- **F-41 (observation, 05):** the spine's single proposer identity holds propose-only grants for every money-moving capability. Each still needs Michael's step-up.

## Safety invariants: HOLD
A1, A2, A3, A4, A5, A7, A9 and A10 all pass. The chain verifies in lane D's verifier and in the ADR-0010 reference alone. Nothing left the system.

## Test changes made, and why (none weakens an assertion)
- **Strict xfails removed** for F-22 and F-23, after confirming each had really flipped.
- **A5 amended per R22.**
  - The settle-truthfully rule is made explicit and stricter than "(a) or (b)": a send that happened must settle `executed`.
  - An earlier test that required "resume" in both crash cases is replaced.
  - The "never two sends" invariant test is kept unchanged.
- **The F-23 regression** now uses `comms.voice.call`, a capability the proposer really lacks. My first attempt used `money.payment.send`, which turned out to be granted (hence F-41). Reading the policy before blaming anyone found that.
- **The publish YES tests** now approve with step-up (the policy's requirement). A separate test asserts the YES-without-step-up refusal that F-40 says is missing.

## Other notes
- A mistake of mine while editing the runner deleted the card-acceptance block; I noticed from the stale report, restored the block from the last commit, and re-ran. The card report is unchanged.
- The cluster cleanup holds: 0 leftover directories or processes after every run.
