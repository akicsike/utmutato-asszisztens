"""Az eredeti PDF-ek és a kivágott képek kiszolgálása.

A UI a forrás PDF-et új fülön nyitja meg a pontos oldalon: /files/<id>.pdf#page=12
(a böngésző beépített PDF-nézője érti a #page=N horgonyt).
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .. import db
from ..paths import file_path, store_root

router = APIRouter(tags=["files"])


@router.get("/files/{doc_id}.pdf")
def get_pdf(doc_id: int) -> FileResponse:
    row = db.fetch_one("SELECT filename FROM documents WHERE id = %s", (doc_id,))
    path = file_path(doc_id)
    if not row or not path.is_file():
        raise HTTPException(404, "nincs ilyen dokumentum")
    return FileResponse(
        path, media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(row['filename'])}",
                 "Cache-Control": "private, max-age=3600"},
    )


@router.get("/images/{image_id}")
def get_image(image_id: int) -> FileResponse:
    row = db.fetch_one("SELECT path FROM images WHERE id = %s", (image_id,))
    if not row:
        raise HTTPException(404, "nincs ilyen kép")
    path = (store_root() / row["path"]).resolve()
    if not path.is_file() or store_root().resolve() not in path.parents:
        raise HTTPException(404, "a kép nem érhető el")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})
