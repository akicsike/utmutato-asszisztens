"""A store szerkezete (STORE_PATH):

  files/<id>.pdf          az eredeti PDF (a UI innen nyitja meg új fülön, a #page=N oldalon)
  docs/<id>/doc.json      DoclingDocument – ebből chunkolunk ("egyszer beolvas, sokszor chunkol")
  docs/<id>/doc.md        a dokumentum Markdownban (előnézet)
  docs/<id>/meta.json     beolvasási adatok
  docs/<id>/pictures/     a Docling által kivágott képek
  uploads/                feltöltés közbeni ideiglenes fájlok
"""

from __future__ import annotations

from pathlib import Path

from .config import get_settings


def store_root() -> Path:
    return Path(get_settings().store_path)


def file_path(doc_id: int) -> Path:
    p = store_root() / "files"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{doc_id}.pdf"


def doc_dir(doc_id: int) -> Path:
    return store_root() / "docs" / str(doc_id)


def uploads_dir() -> Path:
    p = store_root() / "uploads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def seed_root() -> Path:
    return Path(get_settings().seed_path)
