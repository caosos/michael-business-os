"""MOCK — lane B (Discovery, Agent 02). Conforms to Item v1 `sources[]` / `normalized` (ADR-0004).

A fixture SourceAdapter: reads a synthetic raw record from disk instead of a live source, stores the raw
bytes content-addressed (raw_ref), and maps raw → Item v1 normalized fields with Agent 02's canonical
renames (distance_miles → road_miles_one_way, scalar source → sources[]). No network access.
REPLACE WITH: Agent 02's SourceAdapter MCP tools + normalizer.
"""
from __future__ import annotations

import json
import pathlib
import re

from ..core import sha256_ref

IMPLEMENTATION = "MOCK fixture SourceAdapter + normalizer — stands in for Agent 02"
TOOL_NAME, TOOL_VERSION = "mbos_qa.mocks.discovery", "0.1.0"

INJECTION_PATTERNS = re.compile(
    r"ignore (all )?(previous|prior) instructions|wire (a |the )?\$?\d|gift ?card|system prompt|you are now",
    re.IGNORECASE,
)


class ArtifactStore:
    """Content-addressed sha256 store (Agent 04 artifact store stand-in)."""

    def __init__(self, root: str | pathlib.Path):
        self.root = pathlib.Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, data: bytes) -> str:
        ref = sha256_ref(data)
        (self.root / ref.split(":")[1]).write_bytes(data)
        return ref

    def get(self, ref: str) -> bytes:
        return (self.root / ref.split(":")[1]).read_bytes()


def fetch(fixture_path: pathlib.Path, artifacts: ArtifactStore) -> tuple[dict, str]:
    raw_bytes = fixture_path.read_bytes()
    return json.loads(raw_bytes), artifacts.put(raw_bytes)


def source_provenance(pid: str, created_at: str, raw: dict, raw_ref: str) -> dict:
    return {"provenance_id": pid, "created_at": created_at, "actor_type": "external", "agent_name": "agent-02-discovery",
            "basis": "FACT", "source_uri": raw["url"], "fetched_at": raw["fetched_at"],
            "tool_name": TOOL_NAME, "tool_version": TOOL_VERSION, "inputs_used": [{"ref": "raw", "hash": raw_ref}]}


def normalizer_provenance(pid: str, created_at: str, src_pid: str) -> dict:
    return {"provenance_id": pid, "created_at": created_at, "actor_type": "agent", "agent_name": "agent-02-discovery",
            "basis": "FACT", "tool_name": TOOL_NAME + ".normalize", "tool_version": TOOL_VERSION, "derived_from": [src_pid]}


def normalize(raw: dict, raw_ref: str, *, item_id: str, created_at: str, src_pid: str) -> tuple[dict, list[str]]:
    """Return (Item v1 at state DISCOVERED, notes). Notes explain each mapping decision for the report."""
    notes = []
    flags = []
    text = " ".join(str(raw.get(k, "")) for k in ("title", "body", "request"))
    if INJECTION_PATTERNS.search(text):
        flags += ["injection_suspected", "needs_review"]
        notes.append("Prompt-injection pattern found in source text → flags injection_suspected; free text is "
                     "never forwarded to drafts; any action stays tier 0 with untrusted_inputs_present=true.")
    price = {"type": raw["price_type"]}
    if raw.get("price") is not None:
        price["amount"] = float(str(raw["price"]).replace("$", "").replace(",", ""))
        price["currency"] = "USD"
        notes.append(f"price '{raw['price']}' → amount {price['amount']} USD ({raw['price_type']})")
    loc = raw["location"]
    location = {"city": loc["city"], "state": loc["state"], "lat": loc["lat"], "lng": loc["lng"],
                "road_miles_one_way": loc["distance_miles"]}
    notes.append(f"distance_miles {loc['distance_miles']} → normalized.location.road_miles_one_way (ADR-0004 mapping)")
    if loc["distance_miles"] > 100:
        flags.append("long_distance")
    normalized = {
        "title": raw["title"], "condition": raw.get("condition", "unknown"), "price": price, "location": location,
        "counterparty": {"role": raw["counterparty_role"], "contact_method": raw["contact_method"],
                         **({"is_dealer": raw["is_dealer"]} if "is_dealer" in raw else {})},
        "listing_status": raw["listing_status"],
    }
    if flags:
        normalized["flags"] = flags
    band = "lead" if raw["type"] == "service" else f"{int(price.get('amount', 0)) // 500 * 500}-{int(price.get('amount', 0)) // 500 * 500 + 500}"
    item = {
        "item_id": item_id, "schema_version": "1.0.0", "type": raw["type"], "category": raw["category"],
        "subcategory": raw["subcategory"], "opportunity_kind": raw["opportunity_kind"], "state": "DISCOVERED",
        "created_at": created_at,
        "sources": [{
            "source": raw["source"], "url": raw["url"], "ingestion_method": raw["ingestion_method"],
            "first_seen_at": raw["fetched_at"], "raw_ref": raw_ref, "provenance_id": src_pid,
            **({"source_listing_id": raw["source_listing_id"]} if "source_listing_id" in raw else {}),
            **({"tos_risk": raw["tos_risk"]} if "tos_risk" in raw else {}),
        }],
        "dedup_key": f"{raw['category']}|{band}|cell-{loc['lat']:.2f}-{loc['lng']:.2f}",
        "content_hash": sha256_ref({"title": raw["title"], "body": raw.get("body") or raw.get("request")}),
        "normalized": normalized,
        "provenance_ids": [src_pid],
    }
    notes.append(f"source '{raw['source']}' (scalar) → sources[0] with raw_ref {raw_ref[:19]}…")
    notes.append(f"dedup_key = {item['dedup_key']}")
    return item, notes
