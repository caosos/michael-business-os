# Receipt: C-31 read the F-127 shape (lane 03, DRY-RUN)

- FACT: `inputs.py` `_human_entry` reads value and author from `finding` (JSON `{"value","entered_by"}`, author falls back to `source_uri` `human:<id>`), else from the old extra fields. Used by `scope_overrides` and `quote_override`. Entries stay human-attested as before.
- FACT: `tests/test_c31_finding_shape.py` covers both shapes: quote $700 -> YES, $500 -> MAYBE from the new shape; old shape still read; bad JSON/missing value/bool/zero skipped; scope overrides identical across shapes.
- FACT: `cd economics && PYTHONPATH=src:tests python -m pytest tests -q` -> 402 passed, 22 skipped.
- Provenance: READY_QUEUE C-31 and D-32 (coordinator branch). No frozen contract changed. `attestation:` readers need no value so are unchanged.
