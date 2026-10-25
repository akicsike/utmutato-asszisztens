"""Admin: dokumentumok feltöltése, importálása, listázása, újrafeldolgozása, törlése; chunkok és képek."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel

from .. import db, jobs
from ..ingest.metadata import title_from_filename
from ..ingest.pipeline import bump_index
from ..paths import doc_dir, file_path, seed_root, uploads_dir
from .deps import require_admin

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)], tags=["admin"])
MAX_UPLOAD_MB = 200


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def register_file(src: Path, filename: str, source: str, move: bool) -> dict:
    """Egy PDF felvétele: hash (duplikátum kiszűrése) -> documents sor -> files/<id>.pdf -> feldolgozási feladat."""
    digest = _sha256(src)
    existing = db.fetch_one("SELECT id, title, status FROM documents WHERE file_hash = %s", (digest,))
    if existing:
        if move:
            src.unlink(missing_ok=True)
        return {"filename": filename, "status": "duplicate", "document_id": existing["id"], "title": existing["title"]}
    row = db.fetch_one(
        """INSERT INTO documents (title, filename, file_hash, file_size, source)
           VALUES (%s, %s, %s, %s, %s) RETURNING id""",
        (title_from_filename(filename), filename, digest, src.stat().st_size, source),
    )
    target = file_path(row["id"])
    if move:
        shutil.move(str(src), target)
    else:
        shutil.copyfile(src, target)
    jobs.enqueue(row["id"], "process")
    return {"filename": filename, "status": "queued", "document_id": row["id"]}


@router.post("/upload")
async def upload(files: list[UploadFile]) -> dict:
    results = []
    for f in files:
        name = Path(f.filename or "feltoltes.pdf").name
        if not name.lower().endswith(".pdf"):
            results.append({"filename": name, "status": "rejected", "error": "csak PDF tölthető fel"})
            continue
        tmp = uploads_dir() / f"{uuid.uuid4().hex}.pdf"
        size = 0
        with tmp.open("wb") as out:
            while chunk := await f.read(1 << 20):
                size += len(chunk)
                if size > MAX_UPLOAD_MB * 1024 * 1024:
                    break
                out.write(chunk)
        if size > MAX_UPLOAD_MB * 1024 * 1024:
            tmp.unlink(missing_ok=True)
            results.append({"filename": name, "status": "rejected", "error": f"túl nagy (>{MAX_UPLOAD_MB} MB)"})
            continue
        with tmp.open("rb") as check:
            if check.read(5) != b"%PDF-":
                tmp.unlink(missing_ok=True)
                results.append({"filename": name, "status": "rejected", "error": "nem érvényes PDF"})
                continue
        results.append(register_file(tmp, name, "upload", move=True))
    return {"results": results}


@router.post("/import-seed")
def import_seed() -> dict:
    """A kezdő mappa (SEED_HOST_PATH, alapból a projekt hasznalati_utmutatok mappája) PDF-jeinek felvétele."""
    root = seed_root()
    if not root.is_dir():
        raise HTTPException(404, f"a kezdő mappa nem érhető el: {root}")
    results = [register_file(p, p.name, "seed", move=False) for p in sorted(root.rglob("*.pdf"))]
    return {"results": results, "queued": sum(1 for r in results if r["status"] == "queued")}


@router.get("/documents")
def list_documents() -> dict:
    rows = db.fetch_all(
        """SELECT id, title, product, brand, filename, source, pages, status, stage_info, scanned, ocr_pages,
                  parse_seconds, index_seconds, n_chunks, n_images, error, created_at, updated_at, file_size
           FROM documents ORDER BY title"""
    )
    return {"documents": rows, "queue": jobs.queue_status()}


@router.get("/documents/{doc_id}")
def get_document(doc_id: int) -> dict:
    row = db.fetch_one("SELECT * FROM documents WHERE id = %s", (doc_id,))
    if not row:
        raise HTTPException(404, "nincs ilyen dokumentum")
    meta_file = doc_dir(doc_id) / "meta.json"
    row["parse_info"] = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.is_file() else None
    row["chunk_counts"] = db.fetch_all(
        "SELECT strategy, kind, count(*) AS n FROM chunks WHERE document_id = %s GROUP BY strategy, kind ORDER BY 1, 2",
        (doc_id,))
    row["image_counts"] = db.fetch_one(
        """SELECT count(*) AS total,
                  count(*) FILTER (WHERE manual_hidden = FALSE OR (manual_hidden IS NULL AND skipped_reason IS NULL)) AS visible,
                  count(*) FILTER (WHERE description IS NOT NULL) AS described
           FROM images WHERE document_id = %s""", (doc_id,))
    row["jobs"] = db.fetch_all(
        "SELECT id, kind, status, error, created_at, finished_at FROM jobs WHERE document_id = %s ORDER BY id DESC LIMIT 10",
        (doc_id,))
    return row


class DocumentPatch(BaseModel):
    title: str | None = None
    product: str | None = None
    brand: str | None = None


@router.patch("/documents/{doc_id}")
def patch_document(doc_id: int, body: DocumentPatch) -> dict:
    """Kézi javítás (a cím a forrásokban és a chunkok kontextus-előtagjában is szerepel -> újraindexelés)."""
    values = body.model_dump(exclude_none=True)
    if not values:
        return {"ok": True}
    sets = ", ".join(f"{k} = %({k})s" for k in values)
    db.execute(
        f"""UPDATE documents SET {sets}, manual_fields = ARRAY(SELECT DISTINCT unnest(manual_fields || %(fields)s)),
               updated_at = now() WHERE id = %(id)s""",
        {**values, "fields": list(values), "id": doc_id},
    )
    jobs.enqueue(doc_id, "reindex")
    return {"ok": True}


@router.post("/documents/{doc_id}/reprocess")
def reprocess(doc_id: int) -> dict:
    jobs.enqueue(doc_id, "process")
    return {"ok": True}


@router.post("/documents/{doc_id}/reindex")
def reindex(doc_id: int) -> dict:
    jobs.enqueue(doc_id, "reindex")
    return {"ok": True}


@router.post("/reindex-all")
def reindex_all() -> dict:
    ids = [r["id"] for r in db.fetch_all("SELECT id FROM documents WHERE status IN ('indexed', 'error')")]
    for i in ids:
        jobs.enqueue(i, "reindex")
    return {"queued": len(ids)}


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: int) -> dict:
    strategies = [r["strategy"] for r in db.fetch_all(
        "SELECT DISTINCT strategy FROM chunks WHERE document_id = %s", (doc_id,))]
    if not db.execute("DELETE FROM documents WHERE id = %s", (doc_id,)):
        raise HTTPException(404, "nincs ilyen dokumentum")
    shutil.rmtree(doc_dir(doc_id), ignore_errors=True)
    file_path(doc_id).unlink(missing_ok=True)
    bump_index(strategies)
    return {"ok": True}


@router.get("/documents/{doc_id}/chunks")
def document_chunks(doc_id: int, strategy: str = "hybrid") -> dict:
    rows = db.fetch_all(
        """SELECT id, seq, kind, text, embed_text, section, page_from, page_to, image_ids, token_count
           FROM chunks WHERE document_id = %s AND strategy = %s ORDER BY seq""",
        (doc_id, strategy),
    )
    return {"chunks": rows}


@router.get("/documents/{doc_id}/images")
def document_images(doc_id: int) -> dict:
    rows = db.fetch_all(
        """SELECT id, page, width, height, caption, section, ocr_text, description, vlm_model, skipped_reason,
                  manual_hidden FROM images WHERE document_id = %s ORDER BY page, id""",
        (doc_id,),
    )
    return {"images": rows}


class ImagePatch(BaseModel):
    hidden: bool | None  # True = elrejt, False = megjelenít (a szűrés ellenére), None = a szűrés dönt


@router.patch("/images/{image_id}")
def patch_image(image_id: int, body: ImagePatch) -> dict:
    row = db.fetch_one("UPDATE images SET manual_hidden = %s WHERE id = %s RETURNING document_id",
                       (body.hidden, image_id))
    if not row:
        raise HTTPException(404, "nincs ilyen kép")
    jobs.enqueue(row["document_id"], "reindex")
    return {"ok": True}
