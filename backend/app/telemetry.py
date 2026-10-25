"""Phoenix nyomkövetés (OpenTelemetry + OpenInference).

- Az OpenAI-kliens hívásai (chat, embedding) automatikusan LLM / EMBEDDING spanként kerülnek a Phoenixbe,
  tokenszámmal (openinference-instrumentation-openai).
- A saját lépések (átírás, keresés, rerank, a teljes chat-kérés) kézi spanok, OpenInference span-típussal
  (CHAIN, RETRIEVER, RERANKER), így a Phoenix felületén kérdésenként látszik a teljes út és az idők.
- A költséget (OpenRouter `usage.cost`) a gyökér-span attribútumaként is rögzítjük.
Ha a PHOENIX_ENDPOINT üres, minden no-op.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Any, Iterator

from opentelemetry import trace

from .config import get_settings

log = logging.getLogger(__name__)
_initialized = False
TRACER_NAME = "utmutato"


def init_tracing(project: str | None = None) -> None:
    global _initialized
    if _initialized:
        return
    s = get_settings()
    if not s.phoenix_endpoint:
        log.info("Phoenix nyomkövetés kikapcsolva (PHOENIX_ENDPOINT üres)")
        _initialized = True
        return
    try:
        from phoenix.otel import register

        register(project_name=project or s.phoenix_project, endpoint=s.phoenix_endpoint, batch=True,
                 auto_instrument=True, set_global_tracer_provider=True)
        log.info("Phoenix nyomkövetés: %s (projekt: %s)", s.phoenix_endpoint, project or s.phoenix_project)
    except Exception as e:  # a nyomkövetés hibája ne állítsa meg a szolgáltatást
        log.warning("Phoenix nyomkövetés nem indult: %s", e)
    _initialized = True


def tracer():
    return trace.get_tracer(TRACER_NAME)


def _val(v: Any) -> Any:
    if isinstance(v, (str, int, float, bool)):
        return v
    return json.dumps(v, ensure_ascii=False, default=str)


@contextmanager
def span(name: str, kind: str = "CHAIN", input: Any = None, **attrs: Any) -> Iterator[trace.Span]:
    """OpenInference-span: kind = CHAIN | RETRIEVER | RERANKER | LLM | TOOL."""
    with tracer().start_as_current_span(name) as sp:
        sp.set_attribute("openinference.span.kind", kind)
        if input is not None:
            sp.set_attribute("input.value", _val(input))
        for k, v in attrs.items():
            if v is not None:
                sp.set_attribute(k, _val(v))
        yield sp


def set_output(sp: trace.Span, value: Any) -> None:
    sp.set_attribute("output.value", _val(value))


def set_documents(sp: trace.Span, docs: list[dict], prefix: str = "retrieval.documents") -> None:
    """Keresési találatok OpenInference-formában (a Phoenix dokumentumlistaként mutatja)."""
    for i, d in enumerate(docs):
        sp.set_attribute(f"{prefix}.{i}.document.id", str(d.get("id")))
        sp.set_attribute(f"{prefix}.{i}.document.content", (d.get("text") or "")[:2000])
        if d.get("score") is not None:
            sp.set_attribute(f"{prefix}.{i}.document.score", float(d["score"]))
        meta = {k: d.get(k) for k in ("title", "page_from", "page_to", "section", "strategy") if d.get(k) is not None}
        sp.set_attribute(f"{prefix}.{i}.document.metadata", json.dumps(meta, ensure_ascii=False))


def current_trace_id() -> str | None:
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx and ctx.trace_id else None
