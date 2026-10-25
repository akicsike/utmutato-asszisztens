"""Postgres-kapcsolat (pool) és segédfüggvények. A pgvector típus minden kapcsolaton regisztrálva van."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

from pgvector.psycopg import register_vector
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import get_settings

log = logging.getLogger(__name__)
_pool: ConnectionPool | None = None


def _configure(conn: Connection) -> None:
    try:
        register_vector(conn)
    except Exception:  # az első induláskor (migráció előtt) még nincs vector kiterjesztés
        pass


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            get_settings().dsn, min_size=1, max_size=10, kwargs={"row_factory": dict_row},
            configure=_configure, open=True,
        )
    return _pool


def reset_pool() -> None:
    """A migráció után (a vector kiterjesztés létrejötte után) új pool, hogy minden kapcsolaton legyen vector típus."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def conn() -> Iterator[Connection]:
    with pool().connection() as c:
        yield c


def fetch_one(sql: str, params: Any = None) -> dict | None:
    with conn() as c:
        return c.execute(sql, params).fetchone()


def fetch_all(sql: str, params: Any = None) -> list[dict]:
    with conn() as c:
        return c.execute(sql, params).fetchall()


def execute(sql: str, params: Any = None) -> int:
    with conn() as c:
        return c.execute(sql, params).rowcount
