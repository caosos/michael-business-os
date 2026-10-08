# Receipt — READY_QUEUE P-02-13: NHTSA service bulletins (downloaded file) → KB entries

- **Date:** 2026-10-07 · **Actor:** Agent 02 (bounded worker) · **Task source:** READY_QUEUE P-02-13; R23.
- **External effects:** none. DRY-RUN; no network call. The reader takes a local file path.
- **Code:** `src/mbos_discovery/service_bulletins.py` (`collect_bulletins`), reusing the NHTSA admission helpers. Tests: `tests/test_p0213_service_bulletins.py`. Fixture: `tests/fixtures/nhtsa_tsb/` (ILLUSTRATIVE, fictional make FIXMOTORS).
- **Provenance:** every entry cites a FACT record: the operator-supplied download URL (default NHTSA's datasets page) and the sha256 of the file's exact bytes (`raw_ref`, retained in the raw store).

## Acceptance — MET
- "Admitted only with complete fields": a row needs a bulletin number, make, model (≥ 3 chars, not a bare number), a single valid model year, component, summary and a valid date. Fixture: 2 of 9 rows admitted (one entry covers 2012 and 2013).
- "Incomplete stay on the review list": 6 rows are held, each with its reason (no summary, all-years marker 9999, numeric model, instruction-like text, elementary-advice wording, bad date). Instruction-like text excludes the whole summary and no candidate entry is attached.
- "03's `load_kb` accepts them": a test loads the entries through `mbos_economics.valueadd.load_kb`; a covered year matches and an uncovered year is blocked (UNKNOWN).
- Entry wording says a bulletin is a service procedure, not a recall or a finding about the vehicle; whether it was performed is UNKNOWN.
- Full suite: **273 passed, 0 failed, 0 skipped** (was 267).

## UNKNOWN
- The real flat-file column names and encoding. The fixture's layout is modelled from memory; a wrong layout is quarantined, not guessed. Who answers: the first real download.
- Whether the real file puts one model year per row; the reader groups years per bulletin and model.
