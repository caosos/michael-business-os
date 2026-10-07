"""`mbos-discover run` — every source behind one command (B-19), with `--dry`.

Source groups (profile `source` → what it produces):
* items:      ebay, gsa_auctions, samgov, trashnothing, website_lead, referral, govdeals_email,
              publicsurplus_email, estatesales_net_email            → items.json (+ raw/)
* comps:      manual, ebay_marketplace_insights, ebay_browse_asking → comps.json
              (`ebay_browse_asking` is derived from items already stored: no request at all)
* knowledge:  cpsc_recalls, nhtsa                                    → knowledge/<source>.json (entries + review list)

Safety, in this order: the profile's `live` flag (or credentials for eBay; `imap.live` for e-mail) decides whether any
network or mailbox access can happen; the read-only transport allow-lists the host; the policy registry and block freeze
apply to every source. `--fixtures ROOT` serves everything from recorded files. `--dry` runs each adapter against a
RECORDING transport that never touches the network and prints the exact requests a live run would make (secrets
redacted, header NAMES only); it writes no state, reads no PANIC database, and changes no health.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .adapter import SearchProfile
from .adapters import (CpscRecallsAdapter, EbayBrowseAdapter, EbayInsightsAdapter, EmailAlertAdapter, EmlDirReader,
                       GsaAuctionsAdapter, ImapReader, NhtsaAdapter, SamGovAdapter, ServiceIntakeAdapter,
                       TrashNothingAdapter, VehicleQuery)
from .comps import CompsStore, ManualCompsAdapter, asking_comps_from_items, collect_comps
from .health import HealthBook
from .http import HttpResponse, Transport, redact
from .pipeline import run_discovery
from .rawstore import FileRawStore
from .store import ItemStore, load_json, save_json_atomic

ITEM_SOURCES = ("ebay", "gsa_auctions", "samgov", "trashnothing", "website_lead", "referral", "govdeals_email",
                "publicsurplus_email", "estatesales_net_email")
COMP_SOURCES = ("manual", "ebay_marketplace_insights", "ebay_browse_asking")
KNOWLEDGE_SOURCES = ("cpsc_recalls", "nhtsa")
ALL_SOURCES = ITEM_SOURCES + COMP_SOURCES + KNOWLEDGE_SOURCES
EMAIL_SOURCES = ("govdeals_email", "publicsurplus_email", "estatesales_net_email")
DRY_KEY = "DRY-RUN-PLACEHOLDER"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ConfigError(Exception):
    pass


# ---------------------------------------------------------------- dry-run recording
class PlanTransport:
    """Records requests and answers with the smallest valid empty response for the host. Never touches the network."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, list[str], str]] = []

    def request(self, method, url, headers=None, body=None, timeout=20.0) -> HttpResponse:
        self.requests.append((method, redact(url), sorted((headers or {}).keys()), (body or b"").decode("utf-8", "replace")))
        host = url.split("/")[2]
        if method == "POST":
            return HttpResponse(200, b'{"access_token":"dry","expires_in":7200}')
        if host.startswith("api.ebay.com") or host.startswith("api.sandbox.ebay.com"):
            return HttpResponse(200, b'{"itemSales":[]}' if "marketplace_insights" in url else b'{"itemSummaries":[]}')
        body = {"api.gsa.gov": b'{"results":[]}', "trashnothing.com": b'{"posts":[],"num_pages":1}',
                "api.sam.gov": b'{"opportunitiesData":[]}', "www.saferproducts.gov": b"[]",
                "api.nhtsa.gov": b'{"Count":0,"results":[]}'}.get(host, b"{}")
        return HttpResponse(200, body)


class PlanImap:
    """Fake IMAP connection that records the (read-only) command sequence and returns no mail."""

    def __init__(self, host: str, log: list[str]) -> None:
        self.log = log
        log.append(f"connect IMAP4_SSL {host}")

    def login(self, user, password):
        self.log.append(f"LOGIN {user} ***")

    def select(self, folder, readonly=False):
        self.log.append(f"{'EXAMINE' if readonly else 'SELECT'} {folder}  (read-only: {readonly})")
        return "OK", [b"0"]

    def search(self, charset, *criteria):
        self.log.append("SEARCH " + " ".join(map(str, criteria)))
        return "OK", [b""]

    def fetch(self, num, what):  # pragma: no cover — no messages in dry mode
        self.log.append(f"FETCH {num} {what}")
        return "OK", []

    def logout(self):
        self.log.append("LOGOUT")


# ---------------------------------------------------------------- building
@dataclass
class Plan:
    items: list
    comps: list
    knowledge: list                      # (adapter, profile, source name)
    asking: list                         # profiles that derive asking comps from stored items
    dry: "DryLog | None"


class DryLog:
    def __init__(self) -> None:
        self.sections: list[tuple[str, str, PlanTransport | None, list[str]]] = []

    def add(self, source: str, profile_id: str, transport: "PlanTransport | None", notes: list[str]) -> None:
        self.sections.append((source, profile_id, transport, notes))


def _profile(p: Mapping[str, Any]) -> SearchProfile:
    return SearchProfile(profile_id=p["id"], lane=p["lane"], keywords=tuple(p.get("keywords", [])),
                         postal_code=str(p.get("postal_code", "72034")), radius_miles=int(p.get("radius_miles", 100)),
                         max_price=p.get("max_price"), limit=int(p.get("limit", 50)), max_pages=int(p.get("max_pages", 2)))


def _vehicles(p: Mapping[str, Any]) -> list[VehicleQuery]:
    try:
        return [VehicleQuery(str(v["make"]), str(v["model"]), int(v["year"])) for v in p.get("vehicles", [])]
    except (KeyError, ValueError, TypeError) as e:
        raise ConfigError(f"profile {p['id']}: invalid vehicles entry ({e})") from None


def build_plan(cfg: dict, base: Path, fixtures: Path | None, dry: bool, only: set[str], environ=os.environ) -> Plan:
    plan = Plan([], [], [], [], DryLog() if dry else None)
    for p in cfg.get("profile", []):
        src = p["source"]
        if src not in ALL_SOURCES:
            raise ConfigError(f"no adapter implemented for source {src!r} (profile {p['id']})")
        if only and src not in only:
            continue
        prof = _profile(p) if "lane" in p else SearchProfile(p["id"], "flip", tuple(p.get("keywords", [])))
        live = bool(p.get("live", False))
        pt = PlanTransport() if dry else None
        tx: dict[str, Any] = {"transport": pt} if dry else {}
        notes: list[str] = []
        key = lambda name: DRY_KEY if dry else environ.get(name)           # noqa: E731

        if src == "ebay":
            ad = (EbayBrowseAdapter.from_fixture(fixtures / "ebay", _now) if fixtures
                  else EbayBrowseAdapter(key("EBAY_CLIENT_ID"), key("EBAY_CLIENT_SECRET"), environ.get("EBAY_ENV", "production"), clock=_now, **tx))
            if dry:
                notes.append("credentials: EBAY_CLIENT_ID / EBAY_CLIENT_SECRET " + (
                    "set" if environ.get("EBAY_CLIENT_ID") and environ.get("EBAY_CLIENT_SECRET") else "NOT set (a real run fails safely with zero requests)"))
            plan.items.append((ad, prof))
        elif src == "gsa_auctions":
            kw = {"states": frozenset(p["states"])} if p.get("states") else {}
            ad = (GsaAuctionsAdapter.from_fixture(fixtures / "gsa", _now, **kw) if fixtures else
                  GsaAuctionsAdapter(key("GSA_API_KEY"), live=live or dry, clock=_now, **tx, **kw))
            plan.items.append((ad, prof))
        elif src == "samgov":
            st = tuple(p.get("states") or ["AR"])
            ad = (SamGovAdapter.from_fixture(fixtures / "samgov", _now, states=st) if fixtures else
                  SamGovAdapter(key("SAMGOV_API_KEY"), live=live or dry, clock=_now, states=st, **tx))
            plan.items.append((ad, prof))
        elif src == "trashnothing":
            ad = (TrashNothingAdapter.from_fixture(fixtures / "trashnothing", _now) if fixtures else
                  TrashNothingAdapter(key("TRASHNOTHING_API_KEY"), live=live or dry, clock=_now, **tx))
            plan.items.append((ad, prof))
        elif src in ("website_lead", "referral"):
            ad = ServiceIntakeAdapter(src, base / p["inbox"], _now)
            notes.append(f"reads local files in {base / p['inbox']} (no network)")
            plan.items.append((ad, prof))
        elif src in EMAIL_SOURCES:
            imap = p.get("imap") or {}
            if fixtures:
                reader = EmlDirReader(fixtures / "email")
            elif dry and imap:
                log: list[str] = []
                reader = ImapReader(imap["host"], imap["user"], imap.get("password_env", "MBOS_IMAP_PASSWORD"),
                                    imap.get("folder", "INBOX"), live=True, connect=lambda h, _l=log: PlanImap(h, _l),
                                    password=DRY_KEY)                    # placeholder: dry mode never reads the real secret
                notes.append("IMAP password env " + imap.get("password_env", "MBOS_IMAP_PASSWORD") + ": " + (
                    "set" if environ.get(imap.get("password_env", "MBOS_IMAP_PASSWORD")) else "NOT set (a real run fails safely)")
                    + f"; live flag {'ON' if imap.get('live') else 'OFF → a real run opens no connection'}")
                notes.append(("__imap__", log))
            elif imap:
                reader = ImapReader(imap["host"], imap["user"], imap.get("password_env", "MBOS_IMAP_PASSWORD"),
                                    imap.get("folder", "INBOX"), live=bool(imap.get("live", False)))
            elif p.get("mail_dir"):
                reader = EmlDirReader(base / p["mail_dir"])
                notes.append(f"reads local .eml files in {base / p['mail_dir']} (no network)")
            else:
                raise ConfigError(f"profile {p['id']}: e-mail source needs [profile.imap] or mail_dir")
            plan.items.append((EmailAlertAdapter(src, reader, clock=_now), prof))
        elif src == "manual":
            plan.comps.append((ManualCompsAdapter(fixtures / "comps" / "manual" if fixtures else base / p["inbox"], _now), prof))
            notes.append("reads local files (no network)")
        elif src == "ebay_marketplace_insights":
            ad = (EbayInsightsAdapter.from_fixture(fixtures / "comps" / "ebay_insights", _now) if fixtures else
                  EbayInsightsAdapter(key("EBAY_CLIENT_ID"), key("EBAY_CLIENT_SECRET"), environ.get("EBAY_ENV", "production"),
                                      live=live or dry, clock=_now, **tx))
            notes.append("needs eBay Marketplace Insights Limited Release approval (MICHAEL_DECISIONS #8)")
            plan.comps.append((ad, prof))
        elif src == "ebay_browse_asking":
            plan.asking.append(prof)
            notes.append("derived from eBay listings already stored: makes no request")
        elif src == "cpsc_recalls":
            ad = (CpscRecallsAdapter.from_fixture(fixtures / "cpsc", _now) if fixtures else
                  CpscRecallsAdapter(live=live or dry, clock=_now, **tx))
            plan.knowledge.append((ad, prof, src))
        elif src == "nhtsa":
            vs = _vehicles(p)
            if not vs:
                raise ConfigError(f"profile {p['id']}: nhtsa needs `vehicles = [{{make=…, model=…, year=…}}]`")
            ad = (NhtsaAdapter.from_fixture(fixtures / "nhtsa", vs, _now) if fixtures else
                  NhtsaAdapter(vs, live=live or dry, clock=_now, **tx))
            plan.knowledge.append((ad, prof, src))
        if dry:
            if fixtures:
                flag = "fixtures (no network)"
            elif src == "ebay":
                flag = "no per-profile flag: a real run goes live iff credentials are set"
            elif src in EMAIL_SOURCES or src in ("website_lead", "referral", "manual", "ebay_browse_asking"):
                flag = "local / mailbox source"
            else:
                flag = "live flag ON" if live else "live flag OFF → a real run makes 0 requests; the list below is what enabling it would do"
            plan.dry.add(src, p["id"], pt, [flag] + notes)
    return plan


# ---------------------------------------------------------------- dry output
def render_dry(plan: Plan) -> str:
    out: list[str] = []
    for source, pid, pt, notes in plan.dry.sections:
        out.append(f"[dry] {source} · {pid}")
        for n in notes:
            if isinstance(n, tuple):
                out += [f"      IMAP  {line}" for line in n[1]]
            else:
                out.append(f"      {n}")
        if pt is not None:
            for method, url, header_names, body in pt.requests:
                out.append(f"      {method:<4} {url}")
                if header_names:
                    out.append(f"           headers: {', '.join(header_names)}")
                if body:
                    out.append(f"           body: {body}")
            if not pt.requests:
                out.append("      (no requests planned: nothing configured or the profile has no queries)")
    return "\n".join(out)


def dry_run(plan: Plan) -> str:
    """Execute each adapter's fetch against the recording transport (no state, no PANIC, no health)."""
    for ad, prof in plan.items + plan.comps:
        try:
            ad.fetch(prof)
        except Exception:  # noqa: BLE001 — a dry run reports what it can
            pass
    for ad, prof, _ in plan.knowledge:
        try:
            ad.fetch(prof)
        except Exception:  # noqa: BLE001
            pass
    return render_dry(plan)


# ---------------------------------------------------------------- real run
def run(cfg: dict, base: Path, data: Path, fixtures: Path | None, only: set[str], panic, out=print) -> int:
    plan = build_plan(cfg, base, fixtures, False, only)
    hb = HealthBook.from_json(load_json(data / "health.json", {}))
    raw = FileRawStore(data / "raw")
    enabled = frozenset(cfg.get("enabled_sources", []))
    now = _now()

    if plan.items:
        store = ItemStore.from_json(load_json(data / "items.json", {}))
        rep = run_discovery(plan.items, store, raw, hb, now, enabled, panic=panic)
        save_json_atomic(data / "items.json", store.to_json())
        save_json_atomic(data / "runs" / f"{rep.run_id}.json", rep.to_json())
        for s in rep.sources:
            detail = s.skipped_reason or (s.error or {}).get("message")
            out(f"{s.source:<22} {s.profile_id:<22} {s.status:<7} fetched={s.fetched} new={s.created} merged={s.merged} "
                f"updated={s.updated} seen={s.seen} quarantined={s.quarantined}" + (f"  [{detail}]" if detail else ""))
        freezes = list(rep.freeze_requests)
        out(f"items in store: {len(store.items)}  run: {rep.run_id}")
    else:
        freezes = []

    if plan.comps or plan.asking:
        cs = CompsStore.from_json(load_json(data / "comps.json", {}))
        if plan.comps:
            crep = collect_comps(plan.comps, cs, raw, hb, now, enabled, panic=panic)
            for row in crep.sources:
                detail = row.get("reason") or (row.get("error") or {}).get("message")
                out(f"{row['source']:<22} {row['profile_id']:<22} {row['status']:<7} added={row.get('added', 0)} "
                    f"updated={row.get('updated', 0)} seen={row.get('seen', 0)} quarantined={row.get('quarantined', 0)}"
                    + (f"  [{detail}]" if detail else ""))
            freezes += crep.freeze_requests
        if plan.asking:
            items = ItemStore.from_json(load_json(data / "items.json", {})).items.values()
            recs, provs = asking_comps_from_items(list(items))
            for r in recs:
                cs.comps[r["comp_id"]] = r
            for pr in provs:
                cs.provenance.setdefault(pr["provenance_id"], pr)
            out(f"{'ebay_browse_asking':<22} {'(derived)':<22} ok      asking comps={len(recs)}")
        save_json_atomic(data / "comps.json", cs.to_json())
        out(f"comps in store: {len(cs.comps)}")

    for ad, prof, name in plan.knowledge:
        if name == "cpsc_recalls":
            from .recalls import collect_recalls as collector
        else:
            from .vehicle_safety import collect as collector
        krep = collector(ad, prof, raw, hb, now, enabled, panic=panic)
        path = data / "knowledge" / f"{name}.json"
        prev = load_json(path, {})
        merged_records = {**prev.get("records", {}), **krep.records}
        merged_prov = {**prev.get("provenance", {}), **krep.provenance}
        save_json_atomic(path, {"records": merged_records, "provenance": merged_prov, "entries": krep.entries,
                                "review": krep.review, "updated_at": now.isoformat()})
        row = krep.sources[0]
        detail = row.get("reason") or (row.get("error") or {}).get("message")
        out(f"{name:<22} {prof.profile_id:<22} {row['status']:<7} records={len(krep.records)} entries={len(krep.entries)} "
            f"review={len(krep.review)}" + (f"  [{detail}]" if detail else ""))
        freezes += krep.freeze_requests

    save_json_atomic(data / "health.json", hb.to_json())
    for f in freezes:
        out(f"FREEZE REQUEST {f['capability']}: {f['reason']}  (apply: mbos-gov panic freeze --level L2 "
            f"--target {f['capability']} --actor {f['requested_by']} --reason ...)")
    return 0
