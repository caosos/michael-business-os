# Receipt: C-09, sensitivity report for MICHAEL_DECISIONS #1/#2 (Agent 03)

- **Date:** 2026-10-07
- **Task:** `C-09` (READY_QUEUE @ agent-01 `71adb0d`). Claimed at `8cc561f`. Report at `286e0f3`.
- **Scope:** report only. **No config value was changed** (FACT: the script and `tests/test_sensitivity.py` compare sha256 of every config file before and after).

## Outputs
- `docs/research/agent-03-sensitivity-michael-decisions.md`: the decision table, five tagged findings and the full generated tables.
- `economics/src/mbos_economics/sensitivity.py`: in-memory config variants (labelled `<version>+<path>=<value>`), one-at-a-time sweeps and integer-scan break-evens.
- `economics/scripts/sensitivity_report.py`: the generator. The corpus has 19 cases:
  - the 14 goldens
  - Agent 02's 4 service leads (C-01 estimates)
  - Agent 02's Conway trailer with fixture sold comps (C-04)
- `economics/tests/test_sensitivity.py`: 6 tests, including one asserting the published report matches the current config version and hash.

## Key results (FACT, on this illustrative corpus)
- **Flip target:**
  - The round-one trailer is YES only at ≤ $62/h.
  - The same trailer bought at $225 is YES at ≤ $65/h, exactly today's line.
  - The project car is YES up to $90/h.
- **Cash cap:**
  - The project car needs ≥ $1,400 and the truck ≥ $3,000.
  - At $1,000, two deals become PASS.
- **Max-loss cap:** no deal changes verdict between $600 and $1,200.
- **Floor:** between $30 and $50 only one deal changes (the mower, at $39.84/h deterministic).
- **Service target:** equipment repair is YES at ≤ $71, drywall ≤ $87, smart-home ≤ $99. The estimated leads land at EV $66–78/h at the $85 quote placeholder, so decisions #2 and #6 are coupled.

## Caveat (UNKNOWN)
The corpus is illustrative. The counts say which kinds of deal a setting moves, not how often that will happen. Real frequencies need live deal flow plus LEARN (C-07).
