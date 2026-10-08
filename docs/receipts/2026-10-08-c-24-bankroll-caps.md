# Receipt C-24: stale bankroll defaults
Tags: FACT / INFERENCE / UNKNOWN. DRY-RUN; no external action.

- **FACT:** `capital_and_risk.risk_capital_per_deal_cap` **1500 -> 500**, `max_loss_cap` **800 -> 500** (config `2026.10.3` -> `2026.10.4`, changelog entry added, old file in `config/history/`). Source: `config/operator_profile.v1.json` `mission.protected_principal_usd` = 500 (MICHAEL_DECISIONS #1 still undecided). `ev_cap_*` untouched. Engine 0.13.1 -> 0.14.0.
- **FACT:** `engine.effective_caps` gates `cash_ok` / `max_loss_ok` on `min(config cap, economics.context.available_to_deploy)`; absent/null = UNKNOWN keeps the config cap. `inputs.py` validates the field as a number. Failing reason reads "cash tied up $X exceeds the cash you can fund (cap $Y)" and the deal is a hard PASS.
- **FACT:** New `tests/test_bankroll_caps.py`: cap equals profile principal (drift test); a deal tying up >$500 (trailer) is PASS with that reason; `available_to_deploy` lowers the cap, null keeps it. Mechanics goldens that need big-ticket cases use `CFG_BIG` (old 1500/800 caps) in `tests/helpers.py`. Example goldens and the sensitivity report re-baselined at 2026.10.4.
- **FACT:** Training examples: TV $30 MAYBE, MICRO_FLIP, cash_ok; Recon STANDARD_FLIP, cash tied up $467.47, cash_ok (PASS on other grounds, as before); mower CAPITAL_INTENSIVE_FLIP, $868.31 > $500 so hard PASS plus WRONG BUY TODAY.
- **INFERENCE:** The Recon fixture's parts estimate was lowered 150 -> 100 (buy still $300) so it stays fundable; at 150 it tied up $517.47, over the cap. This is a fixture change, not a rule change.
- **Health:** `cd economics && PYTHONPATH=src:tests pytest tests -q` = 359 passed, 22 skipped.
