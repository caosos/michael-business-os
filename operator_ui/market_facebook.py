"""Facebook Marketplace retrieval through the owner's Bright Data dataset.

This module is deliberately small and dependency-free so the Marketplace UI can
read Facebook results without depending on the discovery worker. It never stores
seller/profile/contact fields, caps a request at 20 rows, supports Bright Data's
HTTP 202 snapshot flow, and writes only a local cache consumed by the existing
unified-feed renderer.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://api.brightdata.com/datasets/v3"
DATASET_ID = "gd_lvt9iwuh6fbcwmx1a"
HARD_CAP = 20
STALE_HOURS = 6
REFRESH_MINUTES = 15
TOKEN_FILE = Path("~/.config/mbos/secrets/BRIGHTDATA_TOKEN")
API_KEY_FILE = Path("~/.config/mbos/secrets/BRIGHTDATA_API_KEY")
DEFAULT_CACHE = Path(__file__).resolve().parent.parent / "var" / "cache" / "facebook-marketplace.json"
COMPLIANCE = "UNKNOWN (owner-authorized Bright Data provider route; public listing data only)"
_PRIVATE = re.compile(r"seller|profile|owner|user_?name|user_?id|poster|vendor|contact", re.I)
_ITEM_ID = re.compile(r"/marketplace/item/(\d+)")


class BrightDataError(RuntimeError):
    pass


class BrightDataPending(BrightDataError):
    def __init__(self, snapshot_id: str):
        self.snapshot_id = snapshot_id
        super().__init__("Bright Data snapshot is still running")


def token(path: str | Path | None = None) -> str | None:
    """Read the provider key without ever returning its location to the UI.

    ``BRIGHTDATA_API_KEY`` is Bright Data's documented name.  Keep the older
    ``BRIGHTDATA_TOKEN`` name and file for backward compatibility with the
    first DealSniffer deployment.
    """
    for name in ("BRIGHTDATA_API_KEY", "BRIGHTDATA_TOKEN"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    paths = (Path(path),) if path is not None else (API_KEY_FILE, TOKEN_FILE)
    for candidate in paths:
        try:
            value = candidate.expanduser().read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return None


def cache_path() -> Path:
    return Path(os.environ.get("MBOS_FACEBOOK_CACHE") or DEFAULT_CACHE)


def _clean(value, limit=500) -> str:
    return " ".join(str(value or "").split())[:limit]


def _number(value) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value) if value >= 0 else None
    match = re.search(r"\d[\d,]*(?:\.\d+)?", str(value or ""))
    return float(match.group(0).replace(",", "")) if match else None


def _coordinate(value) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value or ""))
    return float(match.group(0)) if match else None


def _public(value):
    """Recursively drop seller, profile and contact fields before caching."""
    if isinstance(value, dict):
        return {str(k): _public(v) for k, v in value.items() if not _PRIVATE.search(str(k))}
    if isinstance(value, list):
        return [_public(v) for v in value]
    return value


def _rows(body: bytes) -> list[dict]:
    text = body.decode("utf-8", "replace").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        try:
            data = [json.loads(line) for line in text.splitlines() if line.strip()]
        except ValueError as exc:
            raise BrightDataError("Bright Data returned malformed JSON") from exc
    if isinstance(data, dict):
        for key in ("data", "results", "records"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]
    if not isinstance(data, list):
        raise BrightDataError("Bright Data response was not a listing array")
    return [_public(row) for row in data if isinstance(row, dict)]


def _urllib(method: str, url: str, headers: dict, body: bytes | None, timeout: float):
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as response:  # noqa: S310 - fixed Bright Data host only
            return response.status, dict(response.headers), response.read()
    except HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()
    except URLError as exc:
        raise BrightDataError(f"Bright Data network error: {exc.reason}") from exc


class BrightDataClient:
    def __init__(self, api_token: str, *, request: Callable = _urllib, sleep: Callable = time.sleep,
                 max_polls: int = 30, poll_seconds: float = 2.0):
        self._token = api_token.strip()
        self._request = request
        self._sleep = sleep
        self.max_polls = max_polls
        self.poll_seconds = poll_seconds

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}", "Accept": "application/json",
                "Content-Type": "application/json"}

    def _call(self, method: str, url: str, payload: dict | None = None):
        body = json.dumps(payload).encode() if payload is not None else None
        try:
            status, headers, response = self._request(method, url, self.headers, body, 65.0)
        except BrightDataError:
            raise
        except Exception as exc:  # keep provider/transport details but never the secret
            msg = str(exc).replace(self._token, "[redacted]")
            raise BrightDataError(f"Bright Data request failed: {msg}") from exc
        if status in (200, 202):
            return status, headers, response
        detail = response.decode("utf-8", "replace")[:300].replace(self._token, "[redacted]")
        raise BrightDataError(f"Bright Data HTTP {status}: {detail or 'request refused'}")

    @staticmethod
    def _snapshot(body: bytes) -> str:
        try:
            value = json.loads(body.decode("utf-8", "replace"))
            snap = value.get("snapshot_id") if isinstance(value, dict) else None
        except ValueError:
            snap = None
        if not isinstance(snap, str) or not re.fullmatch(r"[A-Za-z0-9_-]{3,120}", snap):
            raise BrightDataError("Bright Data returned HTTP 202 without a usable snapshot_id")
        return snap

    def _poll(self, snap: str) -> list[dict]:
        progress = f"{API}/progress/{snap}"
        for attempt in range(self.max_polls):
            if attempt:
                self._sleep(self.poll_seconds)
            pstatus, _, pbody = self._call("GET", progress)
            if pstatus == 202:
                continue
            try:
                state = json.loads(pbody.decode("utf-8", "replace"))
            except ValueError as exc:
                raise BrightDataError("Bright Data snapshot progress was malformed") from exc
            current = state.get("status") if isinstance(state, dict) else None
            if current == "failed":
                raise BrightDataError("Bright Data snapshot failed")
            if current == "ready":
                dstatus, _, dbody = self._call("GET", f"{API}/snapshot/{snap}?format=json")
                if dstatus != 200:
                    raise BrightDataError("Bright Data snapshot download did not complete")
                return _rows(dbody)
        raise BrightDataPending(snap)

    def resume(self, snapshot_id: str) -> list[dict]:
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,120}", snapshot_id or ""):
            raise BrightDataError("Bright Data pending snapshot ID is invalid")
        return self._poll(snapshot_id)

    def _finish(self, status: int, body: bytes) -> list[dict]:
        if status == 200:
            return _rows(body)
        snap = self._snapshot(body)
        return self._poll(snap)

    def _scrape(self, inputs: list[dict], limit_per_input: int | None = None, *, discover_by: str | None = None) -> list[dict]:
        query = {"dataset_id": os.environ.get("MBOS_BRIGHTDATA_FACEBOOK_DATASET") or DATASET_ID,
                 "include_errors": "true", "format": "json"}
        if discover_by:
            # The live Marketplace collector currently selects its discovery
            # schema with these query flags. Without them, the same dataset ID
            # validates the input as URL collection and rejects ``keyword``.
            query.update({"type": "discover_new", "discover_by": discover_by})
        payload = {"input": inputs}
        if limit_per_input is not None:
            payload["limit_per_input"] = min(max(int(limit_per_input), 1), HARD_CAP)
        status, _, body = self._call("POST", f"{API}/scrape?{urlencode(query)}", payload)
        return self._finish(status, body)

    def search(self, keyword: str, city: str, radius_miles: float, limit: int = HARD_CAP) -> list[dict]:
        cap = min(max(int(limit), 1), HARD_CAP)
        keyword, city = _clean(keyword, 120), _clean(city, 80)
        if not keyword or not city:
            raise BrightDataError("Facebook search needs both a keyword and a ZIP or city")
        # Bright Data's documented Marketplace keyword-discovery schema accepts
        # exactly ``keyword`` in each input object.  City/radius belong to
        # DealSniffer's local filtering and cache identity; sending them to the
        # provider makes an otherwise valid request fail schema validation.
        from . import gazetteer
        provider_city = gazetteer.city_label(city)
        found = self._scrape([{"keyword": keyword, "city": provider_city}], cap, discover_by="keyword")[:cap]
        complete = [row for row in found if row.get("title")]
        urls = [{"url": row["url"]} for row in found if not row.get("title") and isinstance(row.get("url"), str)]
        if urls:
            complete.extend(self._scrape(urls[:cap], 1))
        return [_public(row) for row in complete[:cap] if row.get("title")]


def _loc(row: dict) -> tuple[str | None, str | None, str | None, float | None, float | None]:
    value = row.get("location") or row.get("location_text") or row.get("city")
    data = value if isinstance(value, dict) else {}
    text = _clean(data.get("name") or data.get("text") or value, 100)
    city, state, zip_code = _clean(data.get("city"), 50), _clean(data.get("state"), 2).upper(), _clean(data.get("zip") or data.get("zipcode"), 10)
    match = re.match(r"^\s*([^,]+),\s*([A-Za-z]{2})(?:\s+(\d{5}))?", text)
    if match:
        city, state, zip_code = city or match.group(1), state or match.group(2).upper(), zip_code or (match.group(3) or "")
    lat = _coordinate(data.get("latitude", data.get("lat", row.get("latitude"))))
    lon = _coordinate(data.get("longitude", data.get("lng", data.get("lon", row.get("longitude")))))
    return city or None, state or None, zip_code or None, lat, lon


def _distance(origin, point) -> float | None:
    if not origin or not point or None in point:
        return None
    a1, o1, a2, o2 = map(math.radians, (origin[0], origin[1], point[0], point[1]))
    x = math.sin((a2 - a1) / 2) ** 2 + math.cos(a1) * math.cos(a2) * math.sin((o2 - o1) / 2) ** 2
    return 3958.7613 * 2 * math.asin(math.sqrt(x))


def _image(row: dict) -> str | None:
    values = row.get("images") or [row.get("image_url") or row.get("image")]
    if not isinstance(values, list):
        values = [values]
    for value in values:
        url = value.get("url") if isinstance(value, dict) else value
        if isinstance(url, str) and url.startswith("https://"):
            return url[:2000]
    return None


def cards(rows: list[dict], as_of: str, origin=None) -> list[dict]:
    out = []
    for raw in rows[:HARD_CAP]:
        row = _public(raw)
        title, url = _clean(row.get("title"), 300), _clean(row.get("url"), 2000)
        if not title or not url.startswith("https://www.facebook.com/"):
            continue
        match = _ITEM_ID.search(url)
        ident = _clean(row.get("product_id"), 120) or (match.group(1) if match else hashlib.sha256(url.encode()).hexdigest()[:20])
        price = _number(row.get("final_price"))
        if price is None:
            price = _number(row.get("initial_price", row.get("price")))
        city, state, zip_code, lat, lon = _loc(row)
        point = (lat, lon) if lat is not None and lon is not None else None
        if point is None and (zip_code or (city and state)):
            # Provider rows commonly contain a town but no coordinates.  Use
            # the same local gazetteer as the other Marketplace sources so the
            # owner's radius can be applied instead of silently becoming
            # UNKNOWN.
            from . import gazetteer
            point = gazetteer.locate(zip_code) or gazetteer.locate(f"{city}, {state}")
        description = _clean(row.get("description"), 600)
        condition = _clean(row.get("condition"), 60).lower() or None
        text = f"{title} {description} {condition or ''}".lower()
        posted = _clean(row.get("listing_date"), 40)[:10] or None
        out.append({"id": f"facebook:{ident}", "title": title, "description": description, "text": text, "url": url,
                    "image": _image(row), "bid": price, "price": price, "price_type": "fixed", "bidders": None,
                    "closes": None, "city": f"{city}, {state}" if city and state else city, "state": state, "zip": zip_code,
                    "distance": _distance(origin, point), "category": _clean(row.get("category"), 80) or "other",
                    "condition": condition, "labels": {}, "source": "Facebook Marketplace", "fetched_at": as_of,
                    "kind": "fixed", "stale": False, "fixture": False, "posted": posted, "source_compliance": COMPLIANCE})
    return out


def _read_cache(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) and isinstance(value.get("records"), list) and value.get("as_of") else None
    except (OSError, ValueError):
        return None


def _write_cache(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def _pending_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".pending")


def _read_pending(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) and value.get("snapshot_id") and isinstance(value.get("query"), dict) else None
    except (OSError, ValueError):
        return None


def load(now: datetime, origin=None, *, keyword: str = "", city: str = "", radius: float = 30,
         refresh: bool = False, client: BrightDataClient | None = None, path: Path | None = None) -> dict:
    path = path or cache_path()
    cached = _read_cache(path)
    error = ""
    api_token = token()
    wanted = {"keyword": keyword, "city": city, "radius": radius}
    recent_same = False
    if cached and cached.get("query") == wanted:
        try:
            recent_same = (now - datetime.fromisoformat(str(cached["as_of"]).replace("Z", "+00:00"))).total_seconds() < REFRESH_MINUTES * 60
        except ValueError:
            pass
    if refresh and not recent_same and (client or api_token):
        # The browser request must never sit in a minute-long polling loop.
        # Start/resume once, return the cached feed, then let the page re-check
        # this same snapshot.  This does not create a second paid search.
        active = client or BrightDataClient(api_token, max_polls=1)
        pending_file = _pending_path(path)
        pending = _read_pending(pending_file)
        try:
            rows = active.resume(str(pending["snapshot_id"])) if pending and pending.get("query") == wanted and hasattr(active, "resume") else active.search(keyword, city, radius)
            as_of = now.astimezone(timezone.utc).isoformat(timespec="seconds")
            cached = {"as_of": as_of, "query": wanted,
                      "source_compliance": COMPLIANCE, "records": rows}
            _write_cache(path, cached)
            pending_file.unlink(missing_ok=True)
        except BrightDataPending as exc:
            _write_cache(pending_file, {"as_of": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
                                        "query": wanted, "snapshot_id": exc.snapshot_id, "records": []})
            error = "Bright Data refresh is still running; Search again shortly to resume the same snapshot"
        except BrightDataError as exc:
            error = str(exc)
    if not cached:
        why = error or ("Bright Data token is not configured on this host" if not api_token else "No successful Facebook retrieval is cached")
        return {"status": "offline", "name": "Facebook Marketplace", "as_of": None, "age_h": None, "stale": False,
                "in_scope": 0, "in_file": 0, "cards": [], "fixture": False, "message": why,
                "credential_configured": bool(api_token)}
    as_of = str(cached["as_of"])
    try:
        age = max(0.0, (now - datetime.fromisoformat(as_of.replace("Z", "+00:00"))).total_seconds() / 3600)
    except ValueError:
        age = 10**6
    result = cards(cached["records"], as_of, origin)
    for card in result:
        card["stale"] = age > STALE_HOURS
    refresh_pending = bool(error.startswith("Bright Data refresh is still running"))
    message = (f"Facebook refresh is running; showing the last successful cache. {error}" if refresh_pending else
               f"Live refresh failed; showing the last successful cache. {error}" if error else "")
    return {"status": "connected", "name": "Facebook Marketplace", "as_of": as_of, "age_h": round(age, 1),
            "stale": age > STALE_HOURS, "in_scope": len(result), "in_file": len(cached["records"]), "cards": result,
            "fixture": False, "message": message, "query": cached.get("query"),
            "credential_configured": bool(api_token), "refresh_pending": refresh_pending}


def probe(now: datetime, path: Path | None = None) -> dict:
    data = load(now, path=path)
    return {"status": data["status"], "as_of": data["as_of"], "age_h": data["age_h"],
            "stale": data["stale"], "n": data["in_scope"], "message": data.get("message", ""),
            "credential_configured": data.get("credential_configured", False)}
