# Receipt: F-12, local daily summary (never sent)

- **Date:** 2026-10-07 · **Actor:** Agent 06 · **Task:** READY_QUEUE `F-12` (claimed in `9496c9e`)
- **Intent:** a once-a-day overview for Michael (what to do first, what is parked or overdue, what happened yesterday, which sources are unhealthy), produced locally.
- **Effect:** this branch only. Files are written only to a local directory chosen by the operator. **Nothing is emailed, texted or posted**; no network imports (test-enforced).

## Provenance
| Input | Ref |
|---|---|
| Task | READY_QUEUE @ `a910ad9` |
| Spine | `mbos` @ `a910ad9` (installed from git archive, not merged). Also adopted here: `record_outcome(channel="web")` (P-06-10) |
| Ranking | lane C `mbos_economics.digest` @ `a81a989`, via F-10's `operator_ui/digest.py` (order unchanged) |
| Source health | lane B `health.json` via F-09's `operator_ui/sources.py` |

## What was built
- `operator_ui/summary.py`:
  - `build_summary(store, as_of, top_n, health_file)` builds four sections: digest top-N, HOLD backlog (overdue first), yesterday's outcomes (the previous calendar day in America/Chicago) with net $, and source health (not-healthy sources, staleness).
  - **Every time-dependent choice uses `as_of`**, and every list is sorted explicitly.
  - `summary_hash` is the MBOS-CJSON-1 hash of the assembled data.
- `render_markdown` / `render_html_document`: untrusted text (titles, notes, reasons, remote errors) is escaped for markdown (syntax, pipes, newlines, HTML) and for HTML.
- `write_files(summary, out_dir)` writes `daily-summary-<local date>.md` and `.html` atomically (temp file + rename) and is idempotent.
- CLI: `python -m operator_ui summary --out-dir DIR [--as-of ISO] [--top N]`. UI page: `/summary` (human channel, Host-guarded).

## Verification (FACT)
- `tests/test_summary_f12.py` (7 tests). It uses a **fixture-backed store** (contract example items scored by the real lane-C engine, fixed holds and outcomes, and a health file with a pinned mtime):
  - **byte-identical markdown and HTML across runs and across shuffled input order;** a different `as_of` gives a different hash;
  - section contents, including the local-midnight boundary for "yesterday" (23:59:59 CDT is in, 00:00 CDT is out);
  - stale health and a missing engine are reported;
  - escaping: markdown table structure survives a hostile title containing `|`;
  - atomic local write;
  - no network or send imports;
  - the page and CLI work on the real spine.
- Mutation check: disabling markdown escaping fails the escaping test. The file was restored.
- Full suite: `108 passed`.
