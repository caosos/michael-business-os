"""Lane-07 `ActionPlanner` (ruling R9: lane C recommends, lanes 06/07 draft). Implements `mbos.interfaces.ActionPlanner`.

For a YES item it proposes one DRY-RUN action plus the full draft behind it:
  * flip    → `publish.listing.create`: a resale-listing draft for the manual-assist lane (Marketplace/Craigslist
              have no posting API). It is `partially_reversible`, because a posted listing can be taken down.
  * service → `comms.email.send`: a quote reply to the inbound lead. It is `irreversible` once sent.

The spine contract today only reads {capability, summary, reversibility, estimated_cost}. The extra `draft` key
carries the content, its hash and its G4 provenance (template version, prompt hash, model), so that the spine
can freeze it into the approved payload once finding F-19 is resolved. Deterministic; no LLM; DRY-RUN.
"""
from __future__ import annotations

from typing import Any

from . import drafts

ZERO = {"amount": 0, "currency": "USD"}


def _shape(item: dict[str, Any]) -> dict[str, Any]:
    """`drafts` needs typed fields only, never free text from the listing (prompt-injection hygiene)."""
    n = item.get("normalized") or {}
    loc = n.get("location") or {}
    return {"item_id": item["item_id"], "category": item.get("category"), "subcategory": item.get("subcategory"),
            "normalized": {"title": n.get("title", item.get("category", "item")),
                           "location": {"city": loc.get("city", "the area"), "state": loc.get("state", "")}}}


class MarketingPlanner:
    name = "agent-07-marketing.planner"

    def plan(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        e = item.get("economics") or {}
        shaped = _shape(item)
        if item["type"] == "flip":
            price = (e.get("resale") or {}).get("target_sell_price") or (e.get("resale") or {}).get("comp_price_expected")
            payload = drafts.resale_listing(shaped, price=round(float(price or 0)), platform="Facebook Marketplace",
                                            work_done="to be completed before posting", unknowns="listed as found")
            return [{"capability": "publish.listing.create", "reversibility": "partially_reversible",
                     "summary": f"Resale listing draft (manual-assist, DRY-RUN): {payload['content']['title']}",
                     "estimated_cost": ZERO, "draft": payload}]
        quote = (e.get("job") or {}).get("quoted_revenue") or 0
        payload = drafts.service_quote(shaped, price=round(float(quote)), scope="as described in your request")
        return [{"capability": "comms.email.send", "reversibility": "irreversible",
                 "summary": f"Quote reply draft (DRY-RUN): {payload['content']['subject']}",
                 "estimated_cost": ZERO, "draft": payload}]
