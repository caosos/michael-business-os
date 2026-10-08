# Receipt: G-21b mission dry-run stages 5-8 on the fixed assembly

- Task: G-21b (lane 07 QA). Date 2026-10-08. DRY-RUN only: nothing sent, bought, published or contacted; no other lane touched. `live_effector_calls == 0` (1 effector call, provider `dryrun`, `dry_run true`).
- Provenance: coordinator `fe476b0` in a detached worktree `/tmp/a07g21d/w`; `bootstrap_dev.py --ui-pin g21pin`; fixture `training_examples.json` plus two clone TV listings; Operator UI driven over HTTP (CSRF + nonce + PIN); worker unattended. Evidence and commands: `docs/qa/MISSION_DRYRUN.md` section "G-21b".
- Result: stage 5 PASS, stage 6 PASS, stage 7 PARTIAL, stage 8 PARTIAL.
- Receipt ids: YES `rcpt_01M4EPWA3EYNJ0VRS7NPPGZDNR` (seq 140), executed `rcpt_01M4EPX6FHJAWQKCY25FGTFT25` (146), NO `rcpt_01M4EPSMYB8QM7TN2A5JSDNKY9` (135), HOLD `rcpt_01M4EPSP18G19CWXB0QPF3F9R7` (136), outcome flip_sold `rcpt_01M4EQ0W5H0KJHATT88QCBJVF5` (150, `outc_01M4EQ0W5F3AYEQ8NQ4EQ4M7QN`), capital close ledger seq 2, stuck HOLD YES `rcpt_01M4EQ4FNA82TYNVN1CAC4Q8D7` (152), LEARN draft `areq_01M4EQM2V03JTA1KQKGPQN4897` (denied, never stored).
- Ledger before -> after: principal $500 -> $500; earned $0 -> $60; deployed $0 -> $0; realized $0 -> $60; available $500 -> $560.
- Audit at end: chain ok (152), provenance ok, dry_run ok, conformance ok.
- Findings: F-113 (P3), F-114 (P1: no capital deploy step, so no principal return), F-115 (P2), F-116 (P1: HOLD -> ping -> YES dead end), F-117 (P2), F-118 (P2), F-119 (P3 candidate).
- Cleanup: worker, UI and throwaway cluster stopped (`mbos devdb down`).
