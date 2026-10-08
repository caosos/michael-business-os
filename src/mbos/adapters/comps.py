"""Production comps source for lane C's RESEARCH step (A-39): lane B (Agent 02) comps behind `EconomicsResearcher(comps_source)`.

Three inputs, all read-only and re-read on every call (so a comp Michael adds is seen by the next `mbos recheck`):
- a persisted `CompsStore` JSON (`comps.json`, written by `mbos-discover` comps collection; may already hold asking comps);
- the `ManualCompsAdapter` inbox: JSON files Michael (or the Operator UI for him) entered, normalized by lane B with human provenance;
- asking comps derived from the listings lane B retained (`items.json` beside the store), kind "asking"; lane C fences them as INFER.
`candidate_comps` selects per Item; lane C's `build_comps_bundle` applies the real selection policy. Nothing here touches a network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


class ProductionCompsSource:
    def __init__(self, store_path: Optional[str | Path] = None, inbox: Optional[str | Path] = None, items_path: Optional[str | Path] = None):
        self.store_path = Path(store_path) if store_path else None
        self.inbox = Path(inbox) if inbox else None
        self.items_path = Path(items_path) if items_path else (self.store_path.parent / "items.json" if self.store_path else None)

    def describe(self) -> str:
        parts = []
        if self.store_path:
            parts.append(f"comps store {self.store_path}")
        if self.inbox:
            parts.append(f"manual inbox {self.inbox}")
        if self.items_path and self.items_path.is_file():
            parts.append("asking comps from retained listings (INFER)")
        return " + ".join(parts) if parts else "none"

    def _load(self) -> tuple[dict[str, dict], dict[str, dict]]:
        from mbos_discovery.comps import CompsStore, ManualCompsAdapter, asking_comps_from_items, collect_comps
        from mbos_discovery.adapter import SearchProfile
        from mbos_discovery.health import HealthBook
        from mbos_discovery.rawstore import MemoryRawStore
        from mbos_discovery.store import ItemStore
        from mbos.clock import utcnow

        store = CompsStore()
        if self.store_path and self.store_path.is_file():
            store = CompsStore.from_json(json.loads(self.store_path.read_text()))
        comps, prov = dict(store.comps), dict(store.provenance)
        if self.inbox and self.inbox.is_dir():
            inbox_store = CompsStore()
            collect_comps([(ManualCompsAdapter(self.inbox), SearchProfile(profile_id="manual-inbox", lane="flip"))],
                          inbox_store, MemoryRawStore(), HealthBook(), utcnow())
            comps.update(inbox_store.comps)
            prov.update(inbox_store.provenance)
        if self.items_path and self.items_path.is_file():
            items = ItemStore.from_json(json.loads(self.items_path.read_text())).items.values()
            recs, provs = asking_comps_from_items(list(items))
            for r in recs:
                comps.setdefault(r["comp_id"], r)
            for p in provs:
                prov.setdefault(p["provenance_id"], p)
        return comps, prov

    def __call__(self, item: dict[str, Any]) -> tuple[list[dict], list[dict]]:
        from mbos_discovery.comps import candidate_comps
        from mbos_discovery.ids import parse_ts

        comps, prov = self._load()
        as_of = parse_ts(item.get("updated_at") or item["created_at"])
        chosen = candidate_comps(item, [comps[k] for k in sorted(comps)], as_of)
        return chosen, [prov[c["provenance_id"]] for c in chosen if c.get("provenance_id") in prov]
