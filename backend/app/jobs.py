"""Feladatsor a Postgresben (a worker dolgozza fel). SKIP LOCKED: több worker sem veszi fel kétszer ugyanazt."""

from __future__ import annotations

from . import db


def enqueue(document_id: int, kind: str = "process") -> None:
    exists = db.fetch_one(
        "SELECT 1 FROM jobs WHERE document_id = %s AND kind = %s AND status = 'queued'", (document_id, kind)
    )
    if not exists:
        db.execute("INSERT INTO jobs (document_id, kind) VALUES (%s, %s)", (document_id, kind))


def claim() -> dict | None:
    return db.fetch_one(
        """UPDATE jobs SET status = 'running', started_at = now(), attempts = attempts + 1
           WHERE id = (SELECT id FROM jobs WHERE status = 'queued' ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1)
           RETURNING *"""
    )


def finish(job_id: int, error: str | None = None) -> None:
    db.execute(
        "UPDATE jobs SET status = %s, error = %s, finished_at = now() WHERE id = %s",
        ("error" if error else "done", (error or "")[:4000] or None, job_id),
    )


def recover_stale() -> int:
    """A worker indulásakor: a félbemaradt (running) feladatok újra sorba (pl. a konténer újraindult)."""
    return db.execute("UPDATE jobs SET status = 'queued' WHERE status = 'running'")


def queue_status() -> dict:
    rows = db.fetch_all("SELECT status, count(*) AS n FROM jobs GROUP BY status")
    return {r["status"]: r["n"] for r in rows}
