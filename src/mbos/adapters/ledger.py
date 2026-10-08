"""F-96: the capital ledger as scoring context. `LedgerContext(url)()` returns `{"available_to_deploy": <number>}` read from lane D's
`mbos.capital_position_document('dry_run')`, or `{}` when the ledger is unfunded/unreadable (the engine then keeps its config cap and the
card says UNKNOWN; nothing is ever assumed). Read-only; any worker role may execute it."""

from __future__ import annotations

from typing import Any, Callable, Optional

import sqlalchemy as sa


class LedgerContext:
    def __init__(self, url: str):
        self.engine = sa.create_engine(url, pool_pre_ping=True)

    def __call__(self) -> dict[str, Any]:
        try:
            with self.engine.connect() as c:
                doc = c.execute(sa.text("SELECT mbos.capital_position_document('dry_run')")).scalar()
        except sa.exc.DBAPIError:  # ledger migration absent (reference store) or not readable: UNKNOWN, not an error
            return {}
        if not doc or doc.get("available_to_deploy") is None:
            return {}
        # an unfunded ledger (principal 0) is not "0 available": it is UNKNOWN, so the config cap stays
        if not (doc.get("protected_principal") or doc.get("earned_working_capital")):
            return {}
        return {"available_to_deploy": float(doc["available_to_deploy"])}


def with_context(item: dict[str, Any], source: Optional[Callable[[], dict]]) -> dict[str, Any]:
    """A copy of the Item whose `economics.context` carries the ledger figures (an explicit value already on the Item wins)."""
    ctx = source() if source else {}
    econ = item.get("economics")
    if not ctx or not isinstance(econ, dict):
        return item
    merged = {**ctx, **{k: v for k, v in (econ.get("context") or {}).items() if v is not None}}
    return {**item, "economics": {**econ, "context": merged}}
