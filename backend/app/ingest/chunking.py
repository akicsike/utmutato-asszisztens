"""Chunk-stratégiák a beolvasott DoclingDocument-ből (doc.json) – OCR / Docling újrafuttatása nélkül.
A demo chunking.py-ja alapján.

  hybrid – a dokumentum szerkezete szerint (címsorok, bekezdések, listák, táblázatok – Docling HybridChunker):
           egy chunk egy fejezet(rész); ami túl hosszú, mondathatáron tovább bomlik, a túl rövid szomszédok
           (azonos címsor alatt) összeolvadnak; a táblázat fejléce minden darabban megismétlődik.
  fixed  – alapvonal: a törzsszöveg fix méretű, átfedő tokenablakokban, a szerkezettől függetlenül.
  image  – minden látható képből egy kép-chunk (felirat + VLM-leírás + OCR); minden stratégia indexébe bekerül.

Mindegyiknél:
  text       – a chunk saját szövege (ezt mutatjuk forrásként, ezt kapja az LLM)
  embed_text – kontextus-előtag + fejezetút + szöveg: ez megy az embeddingbe és a BM25-be, így az útmutató
               címe és a terméktípus (pl. "kávégép") minden chunkban kereshető.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer
from docling_core.types.doc import ContentLayer, DoclingDocument, PictureItem, TableItem, TextItem

log = logging.getLogger(__name__)
TEXT_STRATEGIES = ("hybrid", "fixed")
MAX_IMAGES_PER_CHUNK = 4


@dataclass
class Chunk:
    seq: int
    text: str
    embed_text: str
    section: str | None
    page_from: int | None
    page_to: int | None
    token_count: int
    kind: str = "text"
    image_ids: list[int] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


@lru_cache
def get_tokenizer(name: str, max_tokens: int) -> BaseTokenizer:
    """A chunkméretet ugyanazzal a tokenizálóval mérjük, amit az embedding-modell használ (BGE-M3)."""
    from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer

    log.info("chunk-tokenizáló betöltése: %s (max %s token)", name, max_tokens)
    return HuggingFaceTokenizer.from_pretrained(model_name=name, max_tokens=max_tokens)


def context_prefix(meta: dict) -> str:
    """[JURA Impressa S9 kávégép – használati útmutató · kávégép]"""
    parts = [p for p in (meta.get("title"), meta.get("product")) if p]
    return f"[{' · '.join(parts)}]" if parts else ""


def _embed_text(prefix: str, section: str | None, text: str) -> str:
    head = "\n".join(p for p in (prefix, section) if p)
    return f"{head}\n\n{text}" if head else text


def _pages(items) -> tuple[int | None, int | None]:
    pages = [p.page_no for it in items for p in (getattr(it, "prov", None) or [])]
    return (min(pages), max(pages)) if pages else (None, None)


WORD3 = re.compile(r"[^\W\d_]{3,}")


def _denoise(text: str, min_words: int = 2) -> str:
    """OCR-zaj ki: a fotókon / rajzokon "felismert" sorok ("ak", "XN", "£", "-Ww") eldobása. Marad minden sor,
    amiben van szám vagy legalább 3 betűs szó; a chunk egésze kiesik, ha `min_words`-nél kevesebb valódi szava marad."""
    lines = [ln for ln in text.split("\n") if not ln.strip() or re.search(r"\d", ln) or WORD3.search(ln)]
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return out if len(WORD3.findall(out)) >= min_words else ""


def _clean(text: str) -> str:
    return _denoise(text.replace("<!-- image -->", ""))


# ---------------------------------------------------------------------------- hybrid

# Számozott alfejezet-sor, amit a Docling néha listaelemnek vagy sima szövegnek ismer fel címsor helyett
NUMBERED_HEADING = re.compile(r"^(?:[-•]\s*)?(\d{1,2}(?:\.\d{1,2})+)\.?\s+([A-ZÁÉÍÓÖŐÚÜŰ][^\n]{1,90})$")


def _depth(number: str) -> int:
    return number.strip(".").count(".") + 1


def split_numbered_sections(text: str, headings: list[str]) -> list[tuple[list[str], str]]:
    """Egy chunk szétvágása a benne lévő számozott alfejezet-soroknál (különben a "4.7" chunkjába belecsúszik
    a "4.8" szövege is, és az LLM összekeveri őket)."""
    parts: list[tuple[list[str], list[str]]] = [(headings, [])]
    for line in text.split("\n"):
        m = NUMBERED_HEADING.match(line.strip())
        if m and parts[-1][1]:
            depth = _depth(m.group(1))
            base = [h for h in headings if (hm := re.match(r"^(\d+(?:\.\d+)*)\.?\s", h)) and _depth(hm.group(1)) < depth]
            parts.append((base + [f"{m.group(1)} {m.group(2)}".strip()], []))
            continue
        parts[-1][1].append(line)
    out = []
    for hs, lines in parts:
        body = "\n".join(lines).strip()
        if body:
            out.append((hs, body))
    return out or [(headings, text)]


def hybrid_chunks(doc: DoclingDocument, meta: dict, tokenizer: BaseTokenizer) -> list[Chunk]:
    chunker = HybridChunker(tokenizer=tokenizer, merge_peers=True, repeat_table_header=True)
    prefix = context_prefix(meta)
    out: list[Chunk] = []
    for c in chunker.chunk(doc):
        text = _clean(c.text)
        if not text:
            continue
        headings = [h for h in (c.meta.headings or []) if h]
        p_from, p_to = _pages(c.meta.doc_items)
        for hs, body in split_numbered_sections(text, headings):
            section = " > ".join(hs) or None
            embed = _embed_text(prefix, section, body)
            out.append(Chunk(len(out), body, embed, section, p_from, p_to, tokenizer.count_tokens(embed)))
    return out


# ---------------------------------------------------------------------------- fixed

def _inside_table_or_furniture(doc: DoclingDocument, item) -> bool:
    parent = getattr(item, "parent", None)
    while parent is not None:
        try:
            node = parent.resolve(doc)
        except Exception:
            return False
        if isinstance(node, TableItem) or getattr(node, "content_layer", None) == ContentLayer.FURNITURE:
            return True
        parent = getattr(node, "parent", None)
    return False


def _body_units(doc: DoclingDocument) -> list[tuple[str, int | None]]:
    """A törzs elemei sorrendben (szöveg, oldal) – a táblázat Markdownként, a kép a képaláírásával."""
    units: list[tuple[str, int | None]] = []
    for item, _ in doc.iterate_items(included_content_layers={ContentLayer.BODY}):
        if _inside_table_or_furniture(doc, item):
            continue
        page = item.prov[0].page_no if getattr(item, "prov", None) else None
        if isinstance(item, TableItem):
            text = item.export_to_markdown(doc)
        elif isinstance(item, PictureItem):
            text = item.caption_text(doc) if hasattr(item, "caption_text") else ""
        elif isinstance(item, TextItem):
            text = _denoise(item.text, min_words=0)
        else:
            continue
        if text and text.strip():
            units.append((text.strip(), page))
    return units


def fixed_chunks(doc: DoclingDocument, meta: dict, tokenizer: BaseTokenizer, overlap: int) -> list[Chunk]:
    """Fix méretű tokenablak (szavanként mérve), `overlap` token átfedéssel."""
    max_tokens = tokenizer.get_max_tokens()
    prefix = context_prefix(meta)
    budget = int((max_tokens - tokenizer.count_tokens(prefix + "\n\n")) * 0.9)

    words: list[tuple[str, int | None, int]] = []
    for text, page in _body_units(doc):
        for line in text.split("\n"):
            for w in line.split():
                words.append((w, page, tokenizer.count_tokens(w)))
            words.append(("\n", page, 0))
        words.append(("\n", page, 0))

    out: list[Chunk] = []
    start = 0
    while start < len(words):
        end, used = start, 0
        while end < len(words) and (used + words[end][2] <= budget or end == start):
            used += words[end][2]
            end += 1
        window = words[start:end]
        text = re.sub(r" ?\n ?", "\n", " ".join(w for w, _, _ in window))
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if text:
            pages = [p for _, p, _ in window if p is not None]
            embed = _embed_text(prefix, None, text)
            out.append(Chunk(len(out), text, embed, None, min(pages) if pages else None,
                             max(pages) if pages else None, tokenizer.count_tokens(embed)))
        if end >= len(words):
            break
        back, k = 0, end
        while k > start + 1 and back < overlap:
            k -= 1
            back += words[k][2]
        start = k
    return out


# ---------------------------------------------------------------------------- képek

def attach_images(chunks: list[Chunk], images: list[dict]) -> None:
    """A szöveg-chunkhoz az azonos oldal(ak)on lévő képek; ha mindkettőnek van fejezete, az egyezők előre."""
    for c in chunks:
        if c.page_from is None:
            continue
        hits = [im for im in images if im.get("page") and c.page_from <= im["page"] <= (c.page_to or c.page_from)]
        if c.section:
            hits.sort(key=lambda im: 0 if (im.get("section") and im["section"] in c.section) else 1)
        c.image_ids = [im["id"] for im in hits[:MAX_IMAGES_PER_CHUNK]]


def image_chunks(images: list[dict], meta: dict, start_seq: int, image_text) -> list[Chunk]:
    prefix = context_prefix(meta)
    out = []
    for im in images:
        text = image_text(im)
        out.append(Chunk(start_seq + len(out), text, _embed_text(prefix, im.get("section"), text), im.get("section"),
                         im.get("page"), im.get("page"), 0, kind="image", image_ids=[im["id"]]))
    return out


def build_chunks(strategy: str, doc: DoclingDocument, meta: dict, tokenizer: BaseTokenizer, overlap: int) -> list[Chunk]:
    if strategy == "hybrid":
        return hybrid_chunks(doc, meta, tokenizer)
    if strategy == "fixed":
        return fixed_chunks(doc, meta, tokenizer, overlap)
    raise ValueError(f"ismeretlen chunk-stratégia: {strategy}")
