"""SQLAlchemy engines for the app database (Postgres spine)."""

from __future__ import annotations

from functools import lru_cache

import sqlalchemy as sa

from mbos.config import settings


def sqlalchemy_url(url: str) -> str:
    """Accept plain `postgresql://` URLs and pin the psycopg 3 driver."""
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


@lru_cache(maxsize=None)
def engine_for(url: str) -> sa.Engine:
    return sa.create_engine(sqlalchemy_url(url), pool_pre_ping=True, future=True)


def app_engine() -> sa.Engine:
    return engine_for(settings().database_url)
