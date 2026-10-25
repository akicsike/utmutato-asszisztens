"""A RAG-kérdéssor ellenőrzése: az elvárt oldalakon tényleg ott vannak-e a kulcsszavak (és hol máshol)."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, "/app")
from app import db  # noqa: E402

HERE = Path(__file__).parent


def main() -> None:
    items = yaml.safe_load((HERE / "datasets" / "rag_questions.yaml").read_text(encoding="utf-8"))
    bad = 0
    for it in items:
        doc = db.fetch_one("SELECT id FROM documents WHERE filename = %s", (it["doc"],))
        if not doc:
            print(f"{it['id']}: NINCS ilyen dokumentum: {it['doc']}")
            bad += 1
            continue
        pages: set[int] = set()
        for kw in it["keywords"]:
            rows = db.fetch_all(
                """SELECT DISTINCT page_from, page_to FROM chunks
                   WHERE document_id = %s AND strategy = 'hybrid' AND embed_text ILIKE %s""",
                (doc["id"], f"%{kw}%"))
            for r in rows:
                if r["page_from"]:
                    pages.update(range(r["page_from"], (r["page_to"] or r["page_from"]) + 1))
        ok = bool(pages & set(it["pages"]))
        bad += not ok
        print(f"{it['id']}: {'OK ' if ok else 'HIBA'} elvárt {it['pages']}, kulcsszó oldalai: {sorted(pages)}")
    print(f"\n{len(items)} kérdés, {bad} hibás")


if __name__ == "__main__":
    main()
