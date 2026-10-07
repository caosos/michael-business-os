"""REFERENCE action planner — owners: 06 Communications (message drafts) / 07 Marketing (publishing drafts).

Lane C's engine recommends but proposes no actions (by design), so the spine asks a planner what a YES
should turn into. MVP: one first-contact message draft, irreversible, $0, DRY-RUN.
"""

from __future__ import annotations

from typing import Any

ZERO = {"amount": 0, "currency": "USD"}


class DefaultActionPlanner:
    def plan(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        e = item.get("economics") or {}
        card = ((item.get("scores") or {}).get("scorecard") or {})
        if item["type"] == "flip":
            offer = card.get("walk_away_price") or (e.get("acquisition") or {}).get("expected_buy_price")
            ask = f"; offer ${offer:,.0f}" if offer else ""
            summary = f"Ask seller to confirm condition and availability{ask} (DRY-RUN draft)"
        else:
            quote = card.get("min_quote_for_yes") or (e.get("job") or {}).get("quoted_revenue")
            q = f" a ${quote:,.0f} quote and" if quote else ""
            summary = f"Send customer{q} propose a visit time (DRY-RUN draft)"
        return [{"capability": "comms.email.send", "summary": summary, "reversibility": "irreversible",
                 "estimated_cost": ZERO}]
