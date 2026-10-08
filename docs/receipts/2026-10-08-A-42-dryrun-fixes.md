# Receipt: A-42 dry-run fixes (F-102, F-103, F-104, F-105, F-109)

DRY-RUN only. No external action, message, spend or credential change.

Provenance: findings from `docs/qa/MISSION_DRYRUN.md` (Agent 07, G-21a, branch `research/agent-07-marketing`); queue row A-42.

| Finding | Change | Evidence |
|---|---|---|
| F-102 | `EconomicsResearcher` scores with the ledger context at call time only and returns the Item's economics without `context`; `mbos card` adds the ledger figure at display time | `test_a42_researcher_does_not_persist_the_ledger_context`; conformance test |
| F-105 | fixture uses contract basis `UNK`; `spine_d._contract_bases` maps a source's spelled-out `UNKNOWN` to `UNK` before storing | `test_a42_ingested_items_conform_and_raw_payloads_resolve` |
| F-109 | `inbox.ResearchWatcher` (per-item last-seen research length) wired into `mbos worker`; baselines first sight, absorbs the re-check's own entries | `test_a42_research_watcher_wakes_on_new_evidence_once` |
| F-103 | worker report and status lines `flush=True` | code |
| F-104 | `spine_d.retain_raw` mirrors each raw payload under `MBOS_RAW_DIR/sha256/ab/cd/<hex>` (lane B FileRawStore layout); canonical copy stays in the artifact store | test above |

Health: full suite on real PG16 (pgserver): 471 passed, 0 failed. Not run: a full `bootstrap_dev` + `mbos audit` end to end (UNK: covered by the conformance test on lane D only for the fixture item).
Also changed: `tests/integration/test_a41_training_examples.py` basis vocabulary now the contract's FACT|INFER|REC|UNK.
