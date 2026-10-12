# F-164 receipt: /market phone overflow + duplicated state in card location (DRY-RUN, no live reload)

Provenance: queue row F-164 (Agent 01 inspected `478bfc0` in headless Chrome 390x900, `/market?go=1&base=Conway+AR&radius=150`). Reuses F-163 code, no new store.

## What changed (operator_ui/market_browse.py, CSS + `_where`)
- Overflow cause (measured at 360 px): the site header `<nav>` is a no-wrap row inside a no-shrink flex header, and `.mk-main` (a column flex item with `align-items:flex-start`) took its max-content width (457 px). At <=700 px: header/nav `min-width:0` with the nav scrolling inside itself, `.mk`/`.mk-main`/`.mk-side` stretch with `min-width:0`.
- Top bar at <=700 px: form `display:contents`, search box full width, then [Search][Filters] on one row, then count, Sort, View; pills are one row with `overflow-x:auto` (that row only); FIXTURE banner and chips wrap.
- Location: new `_where(card)` renders `City, ST ZIP` once (state appended only when the city does not already end in `, ST`; ZIP only if known and not already in the text). The ` · N mi` suffix is unchanged.
- No `overflow-x:hidden` mask: the test measures `document.scrollingElement.scrollWidth`.

## Tests (tests/test_market_f163.py, +4)
- Real Chrome at 390x900, 360x800 and 1440x900: scrollWidth == viewport width, Search and Filters buttons fully inside, first card top < viewport height.
- Unit: no `, ST, ST` in any card; `_where` cases.
