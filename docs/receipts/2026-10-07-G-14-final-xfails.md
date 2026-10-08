# G-14 receipt: last two strict xfails removed (DRY-RUN)

- **Provenance:** Agent 01 head `944f8e43218de735a36641bc7aa24a6353e94aa4` (`origin/research/agent-01-coordinator`), fetched this run. Re-vendored byte copies: `qa/ext/card.schema.json`, `operator_profile.v1.json`, `qa/ext/seams/*`; `PIN.json` source_commit and sha256s refreshed. `qa/impl_lane_pins.json` `mbos_01` and `qa/impl_spine_PIN` re-pinned from da72f5c to 944f8e4. `install-pins` verified byte identity (mbos @ 944f8e4, mbos_governance @ 716098e).
- **Change:** removed strict xfail on F-69 (`test_each_derived_field_is_unknown_when_only_its_own_input_is_missing`) and F-67 `as-is-above-after-repair`; assertions unchanged. `FINDING_STATUS`: F-67 and F-69 = FIXED (G-14, 01 944f8e4).
- **Results (FACT):** RC READY, 105 passed / 3 skipped / 0 failed; card 457 passed / 0 failed; run 77 passed / 1 xfailed (F-6 KNOWN GAP in test_a03, not in F-51..F-69). Residual xfails for F-51..F-69: **0**.
- Before removing the markers, with the new pin missing (still da72f5c) both tests failed: the pin that matters is `impl_lane_pins.json` `mbos_01`, not `impl_spine_PIN` alone.
- No messages sent, nothing published or spent; CAOSCare untouched.
