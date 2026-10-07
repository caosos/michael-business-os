"""REFERENCE notifier — owner: Lane F Operator UI (06 approval-UX spec). Writes `operator.notify`
outbox rows in the caller's transaction; the Operator UI / ntfy relay consumes them later."""

from __future__ import annotations

from typing import Optional

import sqlalchemy as sa

from mbos.ledger import outbox


class OutboxNotifier:
    def notify(self, conn: sa.Connection, *, kind: str, item_id: str, action_request_id: Optional[str],
               summary: str) -> None:
        outbox(conn, "operator.notify", action_request_id or item_id,
               {"kind": kind, "item_id": item_id, "action_request_id": action_request_id, "summary": summary})
