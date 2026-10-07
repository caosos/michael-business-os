from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    """RFC 3339 UTC with `Z`, the format every contract example uses."""
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def now_iso() -> str:
    return iso(utcnow())


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))
