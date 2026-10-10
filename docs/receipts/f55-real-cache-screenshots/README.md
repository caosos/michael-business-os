# F-55 real-cache screenshots (recurring Arya review deliverable)
Re-run: `.venv/bin/python tools/f55_real_cache_shots.py docs/receipts/f55-real-cache-screenshots` (isolated instance on a loopback ephemeral port, stub store, DRY-RUN, read-only COPY of the existing GSA cache, no live fetch, no external navigation).
Each PNG has a same-named `.json` with: code SHA, URL (port), viewport, active filters, source/cache identity (path, sha256, as-of), capture time, browser. `index.json` lists all; `b19-comparison.json` is the B19 comparison.
- s1: realistic Conway search (REAL_CACHE). s2: tight search, honest zero-result (REAL_CACHE). s3: broader browsing example (REAL_CACHE_BROADER_BROWSING_EXAMPLE, not the realistic search).
- Every scenario has desktop 1648x1000 and mobile 390x844, each first-viewport and full-page. No fabricated listings or photos (GSA cache has none; placeholders shown).
