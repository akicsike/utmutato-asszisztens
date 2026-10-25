"""Képek: a Docling által kivágott képek szűrése, OCR, képleírás (VLM) -> images tábla.

A demo images.py-ja alapján, használati útmutatókra szabva:
  1. a doc.json képei (csak a törzsből: a fej-/lábléc logói furniture-ként eleve kimaradnak)
  2. szűrés: túl kicsi (ikon, vonal, töredék) | ugyanaz a kép sok dokumentumban (logó) | ugyanaz a kép
     a dokumentumon belül többször | dokumentumonkénti darabszám-korlát
  3. "N. ábra" felirat a képhez kötve (a Docling képaláírása, vagy a közeli felirat-sor)
  4. OCR (Tesseract) a képen lévő feliratra (gombnevek, kijelzőszövegek)
  5. VLM-leírás (gpt-4o-mini, OpenRouter) – párhuzamosan, "low detail" módban (olcsó)
Az indexelés a látható képekből kép-chunkot készít, a chatben a válasz alatt galériában jelennek meg.
Az admin kézzel elrejthet / megjeleníthet képet (manual_hidden), az felülírja a szűrést.
"""

from __future__ import annotations

import io
import logging
import re
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from docling_core.types.doc import ContentLayer, DoclingDocument, PictureItem, SectionHeaderItem, TextItem, TitleItem
from PIL import Image, ImageOps
from psycopg.types.json import Jsonb

from .. import db, llm
from ..config import get_settings
from ..paths import doc_dir, store_root

log = logging.getLogger(__name__)
OCR_LANG = {"hu": "hun", "en": "eng", "de": "deu"}
VLM_WORKERS = 8

VLM_SYSTEM = (
    "Használati útmutatókban lévő képeket (ábrák, fotók, kezelőpanelek, alkatrész-rajzok, lépések "
    "illusztrációi) írsz le, hogy a felhasználók szöveges kereséssel megtalálják őket. Csak azt írd le, "
    "ami a képen látszik; ne találgass."
)
VLM_PROMPT = (
    "Útmutató: {doc}\nFejezet: {section}\nKépaláírás: {caption}\n\n"
    "Írd le magyarul 2-4 mondatban, mi látható a képen (pl. kezelőpanel, gomb, kijelző, alkatrész, tartály, "
    "csatlakozó, egy lépés illusztrációja, figyelmeztető jel). Ha olvasható felirat, gombnév, szám vagy jelölés "
    "van rajta, azt szó szerint írd bele. Ne kezdd azzal, hogy 'A képen'."
)
FIGURE_RE = re.compile(r"^\s*(\d{1,3}\.?\s*(ábra|kép|fénykép)|(ábra|kép|fig\.?)\s*\d{1,3}\.?)\s*[:.–-]?\s*\S", re.I)


def dhash(img: Image.Image, size: int = 8) -> str:
    """Különbség-hash (perceptuális): ugyanaz a logó kicsit más felbontásban is ugyanazt adja."""
    g = img.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    px = list(g.tobytes())
    bits = 0
    for row in range(size):
        for col in range(size):
            bits = (bits << 1) | (1 if px[row * (size + 1) + col] > px[row * (size + 1) + col + 1] else 0)
    return f"{bits:016x}"


def ocr_image(path: Path, langs: list[str], min_conf: int = 60) -> str:
    """A képen lévő felirat (Tesseract). Felnagyítva, kontrasztosítva; csak a magabiztos, legalább 3 karakteres
    szavak maradnak, hogy a fotókon talált "zaj" ne kerüljön a keresőbe (a demo beállításai)."""
    if not shutil.which("tesseract"):
        return ""
    lang = "+".join(OCR_LANG.get(x, x) for x in langs) or "hun+eng"
    with Image.open(path) as im0:
        im = im0.convert("L")
    scale = max(1, min(6, 1600 // max(im.size)))
    if scale > 1:
        im = im.resize((im.width * scale, im.height * scale), Image.Resampling.LANCZOS)
    im = ImageOps.autocontrast(im)
    with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
        im.save(tmp.name)
        try:
            out = subprocess.run(["tesseract", tmp.name, "-", "-l", lang, "--psm", "11", "tsv"],
                                 capture_output=True, timeout=90, check=False)
        except subprocess.TimeoutExpired:
            return ""
    lines: dict[tuple, list[str]] = {}
    for row in out.stdout.decode("utf-8", "ignore").splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12:
            continue
        try:
            conf = float(cols[10])
        except ValueError:
            continue
        word = cols[11].strip()
        if conf >= min_conf and sum(ch.isalnum() for ch in word) >= 3:
            lines.setdefault((cols[2], cols[3], cols[4]), []).append(word)
    text = "\n".join(" ".join(ws) for ws in lines.values())
    return text[:2000] if sum(ch.isalpha() for ch in text) >= 6 else ""


def section_paths(doc: DoclingDocument) -> tuple[dict[str, str], dict[str, str]]:
    """Képenként a megelőző címsor(ok) és a közeli "N. ábra: …" felirat (ha a Docling nem kötötte a képhez)."""
    sections: dict[str, str] = {}
    stack: list[tuple[int, str]] = []
    items = [it for it, _ in doc.iterate_items(included_content_layers={ContentLayer.BODY})]

    def caption_at(j: int) -> str | None:
        if 0 <= j < len(items) and isinstance(items[j], TextItem):
            txt = (items[j].text or "").strip()
            if FIGURE_RE.match(txt) and len(txt) < 200:
                return txt
        return None

    pics: list[int] = []
    for idx, item in enumerate(items):
        if isinstance(item, (SectionHeaderItem, TitleItem)):
            lvl = getattr(item, "level", 1) if isinstance(item, SectionHeaderItem) else 0
            while stack and stack[-1][0] >= lvl:
                stack.pop()
            stack.append((lvl, item.text.strip()))
        elif isinstance(item, PictureItem):
            sections[item.self_ref] = " > ".join(t for _, t in stack if t)
            pics.append(idx)

    figures: dict[str, str] = {}
    used: set[str] = set()
    for i in pics:
        for d in (1, -1):  # előbb az utána álló sor (az útmutatókban a felirat jellemzően a kép alatt van)
            cap = caption_at(i + d)
            if cap and cap not in used:
                figures[items[i].self_ref] = cap
                used.add(cap)
                break
    return sections, figures


def _vlm_bytes(path: Path) -> bytes:
    """A VLM-nek kicsinyített JPEG (low detail módban a modell úgyis 512 px-en nézi)."""
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((768, 768))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        return buf.getvalue()


def describe(path: Path, doc_title: str, section: str, caption: str, document_id: int) -> tuple[str | None, str | None]:
    s = get_settings()
    if not s.vlm_model or s.vlm_model == "none":
        return None, None
    try:
        text = llm.vision(
            VLM_PROMPT.format(doc=doc_title or "-", section=section or "-", caption=caption or "-"),
            _vlm_bytes(path), mime="image/jpeg", system=VLM_SYSTEM, model=s.vlm_model, document_id=document_id,
        )
        return (text or None), s.vlm_model
    except Exception as e:  # egy kép hibája ne állítsa meg a többit
        log.warning("képleírás hiba (%s): %s", path.name, e)
        return None, s.vlm_model


def process_images(document_id: int, doc: DoclingDocument, doc_title: str, progress=None) -> dict:
    s = get_settings()
    base = doc_dir(document_id)
    sections, figures = section_paths(doc)
    t0 = time.time()

    manual = {r["item_ref"]: r["manual_hidden"] for r in db.fetch_all(
        "SELECT item_ref, manual_hidden FROM images WHERE document_id = %s AND manual_hidden IS NOT NULL", (document_id,))}
    # a korábbi leírások újrahasznosítása (azonos kép = azonos hash): a VLM pénzbe kerül
    previous = {r["phash"]: r for r in db.fetch_all(
        "SELECT phash, ocr_text, description, vlm_model FROM images WHERE document_id = %s AND description IS NOT NULL",
        (document_id,))}

    rows: list[dict] = []
    seen_in_doc: set[str] = set()
    kept = 0
    for pic in doc.pictures:
        if pic.content_layer != ContentLayer.BODY or not pic.image or not pic.image.uri:
            continue
        file = base / str(pic.image.uri)
        if not file.is_file():
            continue
        with Image.open(file) as im:
            w, h = im.size
            ph = dhash(im)
        prov = pic.prov[0] if pic.prov else None
        rec = {
            "item_ref": pic.self_ref, "page": prov.page_no if prov else None,
            "bbox": prov.bbox.model_dump() if prov else None,
            "caption": (pic.caption_text(doc) or "").strip() or figures.get(pic.self_ref) or None,
            "phash": ph, "width": w, "height": h, "path": str(file.relative_to(store_root())),
            "section": sections.get(pic.self_ref) or None, "skipped_reason": None,
            "ocr_text": None, "description": None, "vlm_model": None,
            "manual_hidden": manual.get(pic.self_ref), "_file": file,
        }
        if min(w, h) < s.image_min_px:
            rec["skipped_reason"] = f"túl kicsi ({w}×{h})"
        elif ph in seen_in_doc:
            rec["skipped_reason"] = "ismétlődő kép a dokumentumon belül"
        else:
            other = db.fetch_one(
                """SELECT count(DISTINCT document_id) AS n FROM images
                   WHERE phash = %s AND document_id <> %s AND skipped_reason IS NULL""", (ph, document_id))["n"]
            if other + 1 >= s.image_repeat_docs:
                rec["skipped_reason"] = f"ismétlődő kép ({other + 1} dokumentumban – logó / sablon?)"
            elif kept >= s.image_max_per_doc:
                rec["skipped_reason"] = f"a dokumentum képszám-korlátja ({s.image_max_per_doc})"
        seen_in_doc.add(ph)
        rec["visible"] = rec["manual_hidden"] is False or (rec["manual_hidden"] is None and rec["skipped_reason"] is None)
        if rec["visible"]:
            kept += 1
        rows.append(rec)

    visible = [r for r in rows if r["visible"]]
    # OCR (CPU) sorban, a VLM (hálózat) párhuzamosan
    for i, r in enumerate(visible):
        prev = previous.get(r["phash"])
        if prev:
            r["ocr_text"], r["description"], r["vlm_model"] = prev["ocr_text"], prev["description"], prev["vlm_model"]
            r["_reused"] = True
        else:
            r["ocr_text"] = ocr_image(r["_file"], s.ocr_lang_list) or None
        if progress:
            progress(f"képek OCR {i + 1}/{len(visible)}")

    todo = [r for r in visible if not r.get("_reused")]
    done = 0
    with ThreadPoolExecutor(max_workers=VLM_WORKERS) as pool:
        futures = {pool.submit(describe, r["_file"], doc_title, r["section"] or "", r["caption"] or "", document_id): r
                   for r in todo}
        for fut, r in futures.items():
            r["description"], r["vlm_model"] = fut.result()
            done += 1
            if progress and (done % 5 == 0 or done == len(todo)):
                progress(f"képleírás {done}/{len(todo)}")

    with db.conn() as c:
        c.execute("DELETE FROM images WHERE document_id = %s", (document_id,))
        for r in rows:
            c.execute(
                """INSERT INTO images (document_id, item_ref, page, bbox, path, width, height, phash, caption, section,
                                       ocr_text, description, vlm_model, skipped_reason, manual_hidden)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (document_id, r["item_ref"], r["page"], Jsonb(r["bbox"]) if r["bbox"] else None, r["path"],
                 r["width"], r["height"], r["phash"], r["caption"], r["section"], r["ocr_text"], r["description"],
                 r["vlm_model"], r["skipped_reason"], r["manual_hidden"]),
            )
    res = {"images": len(rows), "visible": len(visible), "described": len(todo), "seconds": round(time.time() - t0, 1)}
    log.info("képek #%s: %s", document_id, res)
    return res


def visible_images(document_id: int) -> list[dict]:
    """Az indexelésbe kerülő képek (a szűrés és a kézi döntés után)."""
    return db.fetch_all(
        """SELECT * FROM images WHERE document_id = %s
           AND (manual_hidden = FALSE OR (manual_hidden IS NULL AND skipped_reason IS NULL)) ORDER BY page, id""",
        (document_id,),
    )


def image_text(img: dict) -> str:
    """A kép kereshető szövege (a kép-chunk tartalma)."""
    parts = [f"Kép ({img['page']}. oldal)" if img.get("page") else "Kép"]
    if img.get("caption"):
        parts.append(f"Képaláírás: {img['caption']}")
    if img.get("description"):
        parts.append(img["description"])
    if img.get("ocr_text"):
        parts.append("Felirat a képen: " + " ".join(img["ocr_text"].split())[:600])
    return "\n".join(parts)
