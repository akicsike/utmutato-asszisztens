"""Séma-migráció induláskor: az app/migrations/*.sql fájlok sorrendben, mindegyik egyszer.

Az api és a worker is meghívja; a Postgres advisory lock miatt egyszerre csak az egyik futtatja.
Új tábla / oszlop -> új fájl (002_….sql), az adatbázist nem kell törölni.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import psycopg

from .config import get_settings

log = logging.getLogger(__name__)
MIGRATIONS = Path(__file__).parent / "migrations"
LOCK_ID = 707070


def migrate(retries: int = 30) -> None:
    s = get_settings()
    for attempt in range(retries):
        try:
            conn = psycopg.connect(s.dsn, autocommit=True)
            break
        except psycopg.OperationalError:
            if attempt == retries - 1:
                raise
            time.sleep(2)
    with conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_ID,))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, applied_at timestamptz DEFAULT now())"
            )
            done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations").fetchall()}
            for path in sorted(MIGRATIONS.glob("*.sql")):
                if path.name in done:
                    continue
                log.info("migráció: %s", path.name)
                with conn.transaction():
                    conn.execute(path.read_text(encoding="utf-8"))
                    conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))
