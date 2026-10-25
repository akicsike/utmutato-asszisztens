"""PDF -> DoclingDocument (a demo parserének CPU-s, csak PDF-es változata).

- layout-modell, olvasási sorrend, számozott címsorok szintje, TableFormer táblázatok, képkivágás;
- OCR: Tesseract (hun, eng) – a demo mérése szerint az ő/ű betűket helyesen olvassa (az EasyOCR ö/ü-t ad);
  normál módban csak a képként beágyazott szövegre fut, a SZÖVEGRÉTEG NÉLKÜLI PDF-nél (szkennelt / képalapú,
  pl. az RC Cheetah útmutató) a teljes oldalt OCR-ezi (OcrMode.FULL_PAGE);
- képalapú oldalaknál a PyPdfium backend renderel: a Docling alapértelmezett (docling-parse) backendje az
  RC Cheetah szkennelt oldalaiból ÜRES képet adott a Tesseractnak ("Too few characters"), így a 2–5. oldal
  szövege teljesen elveszett; a pypdfium2 ugyanezt hibátlanul rendereli;
- GPU nincs, ezért CPU-n fut (DOCLING_THREADS szállal).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    HeadingHierarchyOptions,
    OcrMode,
    PdfPipelineOptions,
    TesseractCliOcrOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import DoclingDocument

from ..config import get_settings

log = logging.getLogger(__name__)
TESSERACT_LANGS = {"hu": "hun", "en": "eng", "de": "deu"}


@dataclass
class ParseResult:
    document: DoclingDocument
    mode: str                 # standard | fullocr
    scanned: bool
    ocr_pages: list[int]      # szövegréteg nélküli oldalak (1-től számozva)
    page_texts: list[str]     # oldalankénti nyers szövegréteg (a metaadathoz)
    seconds: float
    warnings: list[str] = field(default_factory=list)


def pdf_text_layer(path: Path) -> list[str]:
    """A PDF oldalankénti szövegrétege (pypdfium2) – a képalapú oldalak felismeréséhez."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        return [page.get_textpage().get_text_range() for page in pdf]
    finally:
        pdf.close()


class Parser:
    """Converterek gyorsítótárral: a modellek betöltése drága, ezért módonként egyszer jönnek létre."""

    def __init__(self):
        self.s = get_settings()
        self._converters: dict[str, DocumentConverter] = {}
        self._lock = threading.Lock()

    def _options(self, full_page_ocr: bool) -> PdfPipelineOptions:
        langs = [TESSERACT_LANGS.get(x, x) for x in self.s.ocr_lang_list]
        threads = self.s.docling_threads or os.cpu_count() or 4
        return PdfPipelineOptions(
            accelerator_options=AcceleratorOptions(device="cpu", num_threads=threads),
            document_timeout=self.s.document_timeout_s or None,
            do_ocr=True,
            ocr_options=TesseractCliOcrOptions(lang=langs, mode=OcrMode.FULL_PAGE if full_page_ocr else OcrMode.DEFAULT),
            do_table_structure=True,
            generate_picture_images=True,
            images_scale=self.s.images_scale,
            heading_hierarchy_options=HeadingHierarchyOptions(enabled=True),
        )

    def converter(self, kind: str) -> DocumentConverter:
        """standard: szöveges PDF · mixed: van képalapú oldala is · fullocr: teljesen szkennelt."""
        with self._lock:
            if kind not in self._converters:
                log.info("Docling converter létrehozása: %s", kind)
                opts = self._options(full_page_ocr=(kind == "fullocr"))
                fmt = PdfFormatOption(pipeline_options=opts)
                if kind in ("fullocr", "mixed"):
                    fmt = PdfFormatOption(pipeline_options=opts, backend=PyPdfiumDocumentBackend)
                self._converters[kind] = DocumentConverter(format_options={InputFormat.PDF: fmt})
            return self._converters[kind]

    def parse(self, path: Path) -> ParseResult:
        t0 = time.time()
        page_texts = pdf_text_layer(path)
        n = max(1, len(page_texts))
        chars = sum(len(t.strip()) for t in page_texts)
        min_chars = self.s.scanned_min_chars_per_page
        ocr_pages = [i + 1 for i, t in enumerate(page_texts) if len(t.strip()) < min_chars]
        scanned = chars < min_chars * n
        kind = "fullocr" if scanned else ("mixed" if ocr_pages else "standard")
        result = self.converter(kind).convert(path, raises_on_error=True)
        warnings = [str(getattr(e, "error_message", e)) for e in (getattr(result, "errors", None) or [])]
        return ParseResult(result.document, kind, scanned, ocr_pages, page_texts, time.time() - t0, warnings)
