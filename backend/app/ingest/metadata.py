"""Dokumentum-metaadat: megjeleníthető cím, termék, márka.

A fájlnevek ékezet nélküliek és ömlesztettek („jura-impressa-s9-kavegep-hasznalati-utmutato.pdf”),
ezért egy kis LLM-hívás az első oldalak szövegéből szép, ékezetes címet és terméktípust ad.
A cím a forráslistában jelenik meg, a terméktípus minden chunk kontextus-előtagjába bekerül
(így a „kávégép” szó akkor is kereshető, ha az adott oldal szövegében nem szerepel).
"""

from __future__ import annotations

import json
import logging
import re

from .. import llm
from ..config import get_settings

log = logging.getLogger(__name__)

SYSTEM = (
    "Használati útmutatók metaadatait állapítod meg. Csak a kapott fájlnévből és szövegből dolgozz, "
    "ne találj ki típusszámot. Válaszolj JSON-ban."
)
PROMPT = """Fájlnév: {filename}

Az első oldalak szövege:
{text}

Add vissza JSON-ban:
{{"title": "rövid, ékezetes magyar cím, pl. 'JURA Impressa S9 kávégép – használati útmutató'",
  "product": "a termék típusa egy-két szóban, kisbetűvel, pl. 'kávégép', 'mosogatógép', 'LED TV', 'rádió'",
  "brand": "a gyártó, ha kiderül, különben null"}}"""


def title_from_filename(filename: str) -> str:
    stem = re.sub(r"\.pdf$", "", filename, flags=re.I)
    stem = re.sub(r"^\d{6,}-", "", stem)               # "1755499043-bosch-…"
    stem = re.sub(r"[_\-]+", " ", stem).strip()
    return stem[:1].upper() + stem[1:] if stem else filename


def extract(filename: str, page_texts: list[str], document_id: int | None = None) -> dict:
    fallback = {"title": title_from_filename(filename), "product": None, "brand": None}
    text = "\n".join(t.strip() for t in page_texts[:3] if t.strip())[:3500]
    try:
        raw = llm.chat(
            [{"role": "system", "content": SYSTEM},
             {"role": "user", "content": PROMPT.format(filename=filename, text=text or "(nincs szövegréteg)")}],
            model=get_settings().rewrite_model, purpose="metadata", json_mode=True, max_tokens=200,
            document_id=document_id, temperature=0,
        )
        data = json.loads(raw)
        return {
            "title": (data.get("title") or fallback["title"]).strip()[:200],
            "product": (data.get("product") or None),
            "brand": (data.get("brand") or None),
        }
    except Exception as e:  # LLM nélkül is legyen cím
        log.warning("metaadat-kinyerés hiba (%s): %s", filename, e)
        return fallback
