# Receipt: G-23 third operator audit as Michael, with the full money loop

- Action: ran the audit on two fresh dev assemblies from detached worktrees of coordinator `ccbb265` (`/tmp/a07g23/w`, `/tmp/a07g23/w2`): `tools/bootstrap_dev.py --ui-pin`, `mbos worker --fixture fixtures/sources/training_examples.json`, Operator UI on :8794/:8795, every action posted over HTTP like the browser forms (CSRF + nonce + PIN). DRY-RUN only: nothing sent, bought, published or contacted; no other lane touched; CAOSCare untouched; clusters stopped (`mbos devdb down`), processes killed.
- Provenance: lane pins at bootstrap 04 `1ad83f7`, 05 `44a0fb2`, 03 `3dc8a49`, 02 `a2b971d`, 06 `6173c74`; worker/UI logs, `mbos items/audit`, `mbos.receipts`, UI pages as text. Evidence: `docs/qa/OPERATOR_AUDIT.md` (section "Third audit as Michael ... (G-23)").
- Money loop (TV): YES `rcpt_01M4FDG78T60SVE6WHF9EN9P9Y`, dry-run action `rcpt_01M4FDG7GW3AQSVK6KZDF74WX2`, bought $30 `rcpt_01M4FDK8M72F0B1798DGW52RZP`, outcome sold $92 `rcpt_01M4FDKJKWKQRCVMFD918863KX`. Ledger available $500 -> $470 (deployed $30) -> $562 (earned/profit $62, deployed $0). All PASS.
- Result: jobs 1-5 and 7 PASS, job 6 PARTIAL (HOLD -> wake -> YES FAIL, F-126 P1). Verdict: usable from comp to closed profit; not for a held deal.
- New findings: F-126 (P1), F-127 (P1, audit conformance red after a quote), F-128, F-129, F-130, F-133 (P2), F-131, F-132, F-134, F-135 (P3).
- Health: `mbos_qa spine --rc` 105 passed / 0 failed (3 skipped); `mbos_qa card` 671 passed / 0 failed.
