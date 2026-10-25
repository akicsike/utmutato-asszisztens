"""Háttér-worker: a feladatsor feldolgozása.

  process – teljes feldolgozás: Docling (+OCR) -> metaadat -> képek -> chunkok + embedding
  images  – a képek újrafeldolgozása (szűrés, OCR, leírás), utána újraindexelés
  reindex – csak chunkolás + embedding a mentett doc.json-ból (pl. chunk-beállítás változott)

Egyszerre egy dokumentum (a Docling CPU-n minden magot használ).
"""

from __future__ import annotations

import logging
import time

from . import db, jobs
from .config import get_settings
from .migrate import migrate
from .telemetry import init_tracing, span

log = logging.getLogger("worker")


def run_job(job: dict, parser) -> None:
    from .ingest.pipeline import index_document, process_document, process_document_images

    doc_id = job["document_id"]
    with span(f"ingest:{job['kind']}", "CHAIN", input={"document_id": doc_id, "kind": job["kind"]}):
        if job["kind"] == "process":
            process_document(doc_id, parser)
        elif job["kind"] == "images":
            process_document_images(doc_id)
            index_document(doc_id)
        elif job["kind"] == "reindex":
            index_document(doc_id)
        else:
            raise RuntimeError(f"ismeretlen feladat: {job['kind']}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = get_settings()
    migrate()
    db.reset_pool()
    init_tracing(f"{s.phoenix_project}-ingest")
    stale = jobs.recover_stale()
    if stale:
        log.info("félbemaradt feladatok újra sorba: %s", stale)

    from .ingest.parser import Parser

    parser = Parser()
    log.info("worker elindult")
    while True:
        job = jobs.claim()
        if not job:
            time.sleep(s.worker_poll_s)
            continue
        t0 = time.time()
        log.info("feladat #%s: %s dokumentum #%s", job["id"], job["kind"], job["document_id"])
        try:
            run_job(job, parser)
            jobs.finish(job["id"])
            log.info("feladat #%s kész (%.0fs)", job["id"], time.time() - t0)
        except Exception as e:
            log.exception("feladat #%s hiba", job["id"])
            from .ingest.pipeline import mark_error

            if job["document_id"]:
                mark_error(job["document_id"], f"{type(e).__name__}: {e}")
            jobs.finish(job["id"], f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
