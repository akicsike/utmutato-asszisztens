"""Egy dokumentum feldolgozása végig: PDF -> Docling (+OCR) -> metaadat -> képek -> chunkok + embedding.

"Egyszer beolvas, sokszor chunkol": a chunkolás a mentett doc.json-ból dolgozik, ezért egy chunk-beállítás
megváltoztatása után elég az újraindexelés (`reindex`), nem kell újra OCR-ezni.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path

import numpy as np
from docling_core.types.doc import DoclingDocument, ImageRefMode
from psycopg.types.json import Jsonb

from .. import db, llm
from ..config import get_settings
from ..paths import doc_dir, file_path
from . import metadata
from .chunking import attach_images, build_chunks, get_tokenizer, image_chunks
from .images import image_text, process_images, visible_images
from .parser import Parser

log = logging.getLogger(__name__)
META_FIELDS = ("title", "product", "brand")


def set_status(document_id: int, status: str | None = None, stage: str | None = None) -> None:
    sets, params = ["updated_at = now()"], []
    if status:
        sets.append("status = %s")
        params.append(status)
    sets.append("stage_info = %s")
    params.append(stage)
    params.append(document_id)
    db.execute(f"UPDATE documents SET {', '.join(sets)} WHERE id = %s", params)


def mark_error(document_id: int, error: str) -> None:
    db.execute("UPDATE documents SET status = 'error', stage_info = NULL, error = %s, updated_at = now() WHERE id = %s",
               (error[:4000], document_id))


def bump_index(strategies) -> None:
    for st in strategies:
        db.execute(
            """INSERT INTO index_state (strategy, version) VALUES (%s, 1)
               ON CONFLICT (strategy) DO UPDATE SET version = index_state.version + 1, updated_at = now()""",
            (st,),
        )


def process_document(document_id: int, parser: Parser) -> dict:
    row = db.fetch_one("SELECT * FROM documents WHERE id = %s", (document_id,))
    if row is None:
        raise RuntimeError(f"nincs ilyen dokumentum: {document_id}")
    path = file_path(document_id)
    if not path.is_file():
        raise RuntimeError(f"a fájl nem érhető el: {path}")

    # ---- 1. beolvasás (Docling + OCR)
    db.execute("UPDATE documents SET error = NULL WHERE id = %s", (document_id,))
    set_status(document_id, "parsing", "Docling beolvasás (layout, táblázatok, OCR)")
    result = parser.parse(path)
    doc = result.document

    out = doc_dir(document_id)
    tmp = out.with_name(out.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    doc.save_as_json(tmp / "doc.json", artifacts_dir=Path("pictures"), image_mode=ImageRefMode.REFERENCED)
    (tmp / "doc.md").write_text(doc.export_to_markdown(escape_underscores=False), encoding="utf-8")
    info = {"mode": result.mode, "scanned": result.scanned, "ocr_pages": result.ocr_pages,
            "seconds": round(result.seconds, 1), "warnings": result.warnings,
            "pages": len(doc.pages), "pictures": len(doc.pictures), "tables": len(doc.tables)}
    (tmp / "meta.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.rmtree(out, ignore_errors=True)
    tmp.rename(out)
    # a mentett JSON-t töltjük vissza, hogy a képek útvonalai (pictures/…) a store-ra mutassanak
    doc = DoclingDocument.load_from_json(out / "doc.json")

    # ---- 2. metaadat (az admin által átírt mezők megmaradnak)
    set_status(document_id, None, "metaadat (cím, termék)")
    manual = set(row["manual_fields"] or [])
    meta = metadata.extract(row["filename"], result.page_texts, document_id)
    values = {k: meta[k] for k in META_FIELDS if k not in manual}
    sets = "".join(f", {k} = %({k})s" for k in values)
    db.execute(
        f"""UPDATE documents SET pages = %(pages)s, scanned = %(scanned)s, ocr_pages = %(ocr_pages)s,
                parse_mode = %(mode)s, parse_seconds = %(seconds)s, error = %(warn)s{sets}
            WHERE id = %(id)s""",
        {"pages": len(doc.pages) or None, "scanned": result.scanned, "ocr_pages": result.ocr_pages,
         "mode": result.mode, "seconds": result.seconds, "warn": "; ".join(result.warnings) or None,
         "id": document_id, **values},
    )
    log.info("beolvasva #%s %s: %s, %s oldal, %.0fs, OCR-oldalak: %s", document_id, row["filename"], result.mode,
             len(doc.pages), result.seconds, result.ocr_pages or "-")

    # ---- 3. képek
    process_document_images(document_id, doc)
    # ---- 4. chunkok + embedding
    return index_document(document_id, doc)


def _title(document_id: int) -> tuple[str, dict]:
    row = db.fetch_one("SELECT title, product, brand FROM documents WHERE id = %s", (document_id,))
    return row["title"], {"title": row["title"], "product": row["product"], "brand": row["brand"]}


def process_document_images(document_id: int, doc: DoclingDocument | None = None) -> dict:
    if doc is None:
        doc = DoclingDocument.load_from_json(doc_dir(document_id) / "doc.json")
    title, _ = _title(document_id)
    set_status(document_id, "images", "képek: szűrés, OCR, leírás")
    return process_images(document_id, doc, title, progress=lambda m: set_status(document_id, None, m))


def index_document(document_id: int, doc: DoclingDocument | None = None) -> dict:
    s = get_settings()
    t0 = time.time()
    if doc is None:
        doc = DoclingDocument.load_from_json(doc_dir(document_id) / "doc.json")
    _, meta = _title(document_id)
    set_status(document_id, "indexing", "chunkolás + embedding")
    images = visible_images(document_id)
    tokenizer = get_tokenizer(s.chunk_tokenizer, s.chunk_max_tokens)

    per_strategy = {}
    for strategy in s.strategy_list:
        chunks = build_chunks(strategy, doc, meta, tokenizer, s.chunk_overlap_tokens)
        attach_images(chunks, images)
        chunks += image_chunks(images, meta, len(chunks), image_text)
        per_strategy[strategy] = chunks

    # azonos szöveget (pl. a kép-chunkok minden stratégiában) csak egyszer embeddelünk
    unique = list(dict.fromkeys(c.embed_text for cs in per_strategy.values() for c in cs))
    set_status(document_id, None, f"embedding ({len(unique)} szöveg, {s.embed_model})")
    vectors = dict(zip(unique, llm.embed(unique, model=s.embed_model, document_id=document_id)))

    with db.conn() as c:
        c.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
        for strategy, chunks in per_strategy.items():
            for ch in chunks:
                cid = c.execute(
                    """INSERT INTO chunks (document_id, strategy, seq, kind, text, embed_text, section, page_from,
                                           page_to, image_ids, token_count, extra)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                    (document_id, strategy, ch.seq, ch.kind, ch.text, ch.embed_text, ch.section, ch.page_from,
                     ch.page_to, ch.image_ids, ch.token_count, Jsonb(ch.extra) if ch.extra else None),
                ).fetchone()["id"]
                c.execute("INSERT INTO embeddings (chunk_id, model, embedding) VALUES (%s, %s, %s)",
                          (cid, s.embed_model, np.asarray(vectors[ch.embed_text], dtype=np.float32)))
        n_text = sum(1 for ch in per_strategy.get(s.chat_strategy, []) if ch.kind == "text")
        c.execute(
            """UPDATE documents SET status = 'indexed', stage_info = NULL, n_chunks = %s, n_images = %s,
                      index_seconds = %s, updated_at = now() WHERE id = %s""",
            (n_text, len(images), time.time() - t0, document_id),
        )
    bump_index(per_strategy.keys())
    res = {st: len(cs) for st, cs in per_strategy.items()}
    log.info("indexelve #%s: %s chunk, %s kép, %.1fs", document_id, res, len(images), time.time() - t0)
    return res
