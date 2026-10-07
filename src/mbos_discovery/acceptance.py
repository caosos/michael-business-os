"""Discovery acceptance F1–F4 as a runnable harness — READY_QUEUE B-10 (agent-01-integration §8-F).

    mbos-discover acceptance --corpus tests/fixtures/corpus7d [--out report.json]

F1  every Item has ≥ 1 `sources[]` entry and every entry has a `raw_ref` whose bytes are retained and hash-verified.
F2  duplicate rate after dedup over a 7-day corpus (target < 2%), photos used as evidence when present (B-11; the
    listing-data-only result is reported alongside). With ground-truth labels (`labels.json`, never seen by the
    pipeline) mapping each sighting to its physical object,
        missed_duplicate_rate = (Items − distinct objects covered) / Items          — target < 0.02
        false_merge_rate      = Items whose sightings span > 1 object / Items        — must be 0
F3  a source answering 403/429 twice produces one schema-valid L2 freeze request (`discovery.source.<src>.read`), and
    the next run makes zero requests to it.
F4  no collector touches a do-not-automate source: every FORBIDDEN source is refused before fetch even when
    "enabled", and no shipped adapter's read-only transport allow-lists a forbidden site's host.

Runs fully offline on fixtures (real adapters, fixture transports). Exit code 1 if any check fails.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .adapter import FetchResult, SearchProfile, SourceAdapter
from .adapters import (EbayBrowseAdapter, EbayInsightsAdapter, EmailAlertAdapter, EmlDirReader, GsaAuctionsAdapter,
                       SamGovAdapter, ServiceIntakeAdapter, TrashNothingAdapter)
from .health import HealthBook
from .ids import sha256_ref
from .pipeline import run_discovery
from .policy import REGISTRY, Disposition
from .rawstore import MemoryRawStore
from .store import ItemStore

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
F2_TARGET = 0.02
FORBIDDEN_HOSTS = ("facebook.com", "nextdoor.com", "thumbtack.com", "angi.com", "homeadvisor.com",
                   "estatesales.net", "estatesales.org")


class _Clock:
    def __init__(self, t: datetime) -> None:
        self.t = t

    def __call__(self) -> datetime:
        return self.t


def _corpus_jobs(day: Path, clock) -> list[tuple[SourceAdapter, SearchProfile]]:
    flip = SearchProfile("corpus-flip", "flip", ("trailer", "equipment"), limit=200, max_pages=1)
    svc = SearchProfile("corpus-service", "service")
    return [
        (EbayBrowseAdapter.from_fixture(day / "ebay", clock), flip),
        (GsaAuctionsAdapter.from_fixture(day / "gsa", clock), SearchProfile("corpus-gsa", "flip")),
        (EmailAlertAdapter("govdeals_email", EmlDirReader(day / "email"), clock=clock), SearchProfile("corpus-mail", "flip")),
        (ServiceIntakeAdapter("website_lead", day / "intake" / "website_form", clock), svc),
        (ServiceIntakeAdapter("referral", day / "intake" / "referral", clock), svc),
    ]


def image_fetcher(corpus: Path):
    """Fixture photos (B-11) if the corpus has them and Pillow is installed; else None (listing data only)."""
    idx = corpus / "images" / "index.json"
    try:
        import PIL  # noqa: F401
    except ImportError:
        return None
    if not idx.exists():
        return None
    from .images import FixtureImageFetcher
    return FixtureImageFetcher({u: corpus / rel for u, rel in json.loads(idx.read_text()).items()})


def run_corpus(corpus: Path, use_images: bool = True) -> tuple[ItemStore, MemoryRawStore, list]:
    store, raw, health, reports = ItemStore(), MemoryRawStore(), HealthBook(), []
    fetcher = image_fetcher(corpus) if use_images else None
    days = sorted(p for p in corpus.iterdir() if p.is_dir() and p.name.startswith("day"))
    for i, day in enumerate(days):
        clock = _Clock(T0 + timedelta(days=i))
        reports.append(run_discovery(_corpus_jobs(day, clock), store, raw, health, clock(), images=fetcher))
    return store, raw, reports


def check_f1(store: ItemStore, raw: MemoryRawStore) -> dict:
    bad = []
    for item in store.items.values():
        if not item.get("sources"):
            bad.append(f"{item['item_id']}: no sources")
        for s in item.get("sources", []):
            ref = s.get("raw_ref")
            if not ref or not raw.exists(ref) or sha256_ref(raw.get(ref)) != ref:
                bad.append(f"{item['item_id']}: sighting {s.get('source')}:{s.get('source_listing_id')} raw_ref invalid")
    return {"pass": not bad and bool(store.items), "items": len(store.items), "violations": bad}


def check_f2(store: ItemStore, labels: dict[str, str]) -> dict:
    unlabeled, false_merges, covered = [], [], set()
    for item in store.items.values():
        objs = set()
        for s in item["sources"]:
            obj = labels.get(f"{s['source']}|{s['source_listing_id']}")
            if obj is None:
                unlabeled.append(f"{s['source']}|{s['source_listing_id']}")
            else:
                objs.add(obj)
        if len(objs) > 1:
            false_merges.append({"item_id": item["item_id"], "objects": sorted(objs)})
        covered |= objs
    n = len(store.items)
    by_obj: dict[str, list[str]] = {}
    for item in store.items.values():
        for o in {labels.get(f"{s['source']}|{s['source_listing_id']}") for s in item["sources"]} - {None}:
            by_obj.setdefault(o, []).append(item["item_id"])
    missed = {o: sorted(ids) for o, ids in sorted(by_obj.items()) if len(ids) > 1}
    rate = (n - len(covered)) / n if n else 0.0
    return {"pass": rate < F2_TARGET and not false_merges and not unlabeled,
            "items": n, "objects": len(covered), "sightings_labelled": len(labels),
            "missed_duplicate_rate": round(rate, 4), "target": F2_TARGET,
            "false_merge_rate": round(len(false_merges) / n, 4) if n else 0.0,
            "missed_duplicates": missed, "false_merges": false_merges, "unlabeled": unlabeled}


class _Blocking(SourceAdapter):
    source, ingestion_method, tos_risk, access_tier, adapter_version = "gsa_auctions", "api", "low", 1, "f3"
    lanes = frozenset({"flip"})

    def __init__(self, status: int) -> None:
        self.status, self.calls = status, 0

    def fetch(self, profile):
        from .adapter import SourceError
        self.calls += 1
        kind = "rate_limited" if self.status == 429 else "blocked"
        return FetchResult(self.source, error=SourceError(kind, f"HTTP {self.status}", self.status), requests_made=1)

    def normalize(self, payload, fetched_at):  # pragma: no cover - never reached
        raise AssertionError


def check_f3(schema_path: Path | None = None) -> dict:
    out = {}
    validator = None
    if schema_path and schema_path.exists():
        from jsonschema import Draft202012Validator
        validator = Draft202012Validator(json.loads(schema_path.read_text()))
    for status in (403, 429):
        ad, health, prof = _Blocking(status), HealthBook(), SearchProfile("f3", "flip")
        reqs = []
        for i in range(3):
            rep = run_discovery([(ad, prof)], ItemStore(), MemoryRawStore(), health, T0 + timedelta(minutes=i))
            reqs += rep.freeze_requests
        valid = all(not list(validator.iter_errors(r)) for r in reqs) if validator else True
        out[str(status)] = {"freeze_requests": len(reqs), "capability": reqs[0]["capability"] if reqs else None,
                            "fetches": ad.calls, "schema_valid": valid}
    ok = all(v["freeze_requests"] == 1 and v["fetches"] == 2 and v["schema_valid"]
             and v["capability"] == "discovery.source.gsa_auctions.read" for v in out.values())
    return {"pass": ok, "by_status": out, "schema_checked": validator is not None}


def check_f4() -> dict:
    forbidden = sorted(s for s, p in REGISTRY.items() if p.disposition is Disposition.FORBIDDEN)
    touched = []
    for src in forbidden:
        class _Probe(_Blocking):
            source = src
        probe = _Probe(200)
        run_discovery([(probe, SearchProfile("f4", "flip"))], ItemStore(), MemoryRawStore(), HealthBook(), T0,
                      enabled_sources=frozenset({src}))
        if probe.calls:
            touched.append(src)
    adapters = [EbayBrowseAdapter("x", "y"), EbayInsightsAdapter("x", "y"), GsaAuctionsAdapter("k"),
                TrashNothingAdapter("k"), SamGovAdapter("k")]
    leaks = []
    for ad in adapters:
        hosts = set(ad.http._get_hosts) | {u.split("/")[2] for u in ad.http._token_urls}
        leaks += [f"{ad.source}: {h}" for h in hosts if any(h == f or h.endswith("." + f) for f in FORBIDDEN_HOSTS)]
    return {"pass": not touched and not leaks and len(forbidden) >= 8, "forbidden_sources": forbidden,
            "fetched_despite_forbidden": touched, "forbidden_hosts_allow_listed": leaks}


def run_acceptance(corpus: Path, schema_path: Path | None = None) -> dict:
    labels = json.loads((corpus / "labels.json").read_text())
    images_used = image_fetcher(corpus) is not None
    store, raw, _ = run_corpus(corpus, use_images=True)
    f2 = check_f2(store, labels)
    f2["image_evidence"] = images_used
    if images_used:                                       # what listing data alone would do (B-11 comparison)
        plain, _, _ = run_corpus(corpus, use_images=False)
        base = check_f2(plain, labels)
        f2["listing_data_only"] = {k: base[k] for k in ("items", "objects", "missed_duplicate_rate",
                                                        "false_merge_rate", "false_merges")}
    report = {"corpus": str(corpus), "F1": check_f1(store, raw), "F2": f2,
              "F3": check_f3(schema_path), "F4": check_f4()}
    report["pass"] = all(report[k]["pass"] for k in ("F1", "F2", "F3", "F4"))
    return report


def render(report: dict) -> str:
    f2 = report["F2"]
    rows = [
        ("F1", report["F1"]["pass"], f"{report['F1']['items']} Items, {len(report['F1']['violations'])} violations"),
        ("F2", f2["pass"], f"missed-duplicate rate {f2['missed_duplicate_rate']:.2%} (target < {f2['target']:.0%}); "
                           f"false merges {len(f2['false_merges'])}; {f2['items']} Items / {f2['objects']} objects; "
                           + ("photos used" + (f" (listing data alone: {len(f2['listing_data_only']['false_merges'])} "
                                               "false merge(s))" if "listing_data_only" in f2 else "")
                              if f2.get("image_evidence") else "no photo evidence")),
        ("F3", report["F3"]["pass"], "; ".join(f"{k}: {v['freeze_requests']} request(s), {v['fetches']} fetches"
                                               for k, v in report["F3"]["by_status"].items())),
        ("F4", report["F4"]["pass"], f"{len(report['F4']['forbidden_sources'])} forbidden sources refused; "
                                     f"{len(report['F4']['forbidden_hosts_allow_listed'])} forbidden hosts allow-listed"),
    ]
    lines = ["| Check | Result | Detail |", "|---|---|---|"] + [f"| {c} | {'PASS' if ok else 'FAIL'} | {d} |" for c, ok, d in rows]
    return "\n".join(lines) + f"\n\nOverall: {'PASS' if report['pass'] else 'FAIL'}"
