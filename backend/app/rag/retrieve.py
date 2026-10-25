"""Hibrid keresés: dense (pgvector, koszinusz) + BM25 -> RRF -> rerank (Cohere, OpenRouter) -> top-k.

Minden lépés kapcsolható (a RAG-szintű mérés így veti össze: csak dense / csak BM25 / hibrid, rerankkel
vagy nélküle, chunk-stratégiánként és embedding-modellenként).
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field

import numpy as np

from .. import db, llm
from ..config import get_settings
from ..telemetry import set_documents, set_output, span
from .bm25 import get_index

log = logging.getLogger(__name__)


@dataclass
class Hit:
    chunk_id: int
    document_id: int
    title: str
    product: str | None
    kind: str
    text: str
    section: str | None
    page_from: int | None
    page_to: int | None
    image_ids: list[int]
    rrf: float = 0.0
    dense_rank: int | None = None
    bm25_rank: int | None = None
    rerank_score: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RetrievalResult:
    query: str
    hits: list[Hit]
    weak: list[Hit] = field(default_factory=list)   # ha semmi nem éri el a küszöböt: a legjobbak (megnevezéshez)
    timings_ms: dict = field(default_factory=dict)
    config: dict = field(default_factory=dict)


def dense_search(vector: list[float], strategy: str, model: str, limit: int) -> list[tuple[int, float]]:
    vec = np.asarray(vector, dtype=np.float32)
    rows = db.fetch_all(
        """SELECT c.id, 1 - (e.embedding <=> %(v)s) AS sim
           FROM embeddings e JOIN chunks c ON c.id = e.chunk_id
           WHERE e.model = %(m)s AND c.strategy = %(s)s
           ORDER BY e.embedding <=> %(v)s LIMIT %(n)s""",
        {"v": vec, "m": model, "s": strategy, "n": limit},
    )
    return [(r["id"], float(r["sim"])) for r in rows]


def rrf_merge(ranked_lists: list[list[int]], k: int) -> dict[int, float]:
    """Reciprocal Rank Fusion: score = Σ 1 / (k + rank). A rangsor számít, nem a (más skálájú) pontszám."""
    scores: dict[int, float] = {}
    for lst in ranked_lists:
        for rank, cid in enumerate(lst, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return scores


def load_hits(chunk_ids: list[int]) -> dict[int, Hit]:
    if not chunk_ids:
        return {}
    rows = db.fetch_all(
        """SELECT c.id, c.document_id, c.kind, c.text, c.section, c.page_from, c.page_to, c.image_ids,
                  d.title, d.product
           FROM chunks c JOIN documents d ON d.id = c.document_id WHERE c.id = ANY(%s)""",
        (chunk_ids,),
    )
    return {r["id"]: Hit(r["id"], r["document_id"], r["title"], r["product"], r["kind"], r["text"], r["section"],
                         r["page_from"], r["page_to"], list(r["image_ids"] or [])) for r in rows}


MAX_IMAGE_HITS = 2


def cap_images(hits: list[Hit], top_k: int) -> list[Hit]:
    """Legfeljebb MAX_IMAGE_HITS kép-chunk (VLM-leírás) a top-k-ban: a képleírás a szöveghez hasonló pontot kap a
    rerankertől, de kevesebb tényt tartalmaz – a mérésben kiszorította a "Töltés" fejezet szövegét."""
    out, n_img = [], 0
    for h in hits:
        if h.kind == "image":
            if n_img >= MAX_IMAGE_HITS:
                continue
            n_img += 1
        out.append(h)
        if len(out) >= top_k:
            break
    return out


def rerank_text(h: Hit) -> str:
    head = " · ".join(p for p in (h.title, h.section) if p)
    return f"{head}\n{h.text}" if head else h.text


def retrieve(query: str, strategy: str | None = None, model: str | None = None, top_k: int | None = None,
             use_dense: bool = True, use_bm25: bool = True, use_rerank: bool = True,
             min_score: float | None = None, message_id: str | None = None,
             keywords: list[str] | None = None) -> RetrievalResult:
    """`keywords`: az átíró LLM útmutató-szókincsű kulcsszavai – csak a BM25-lekérdezést bővítik (a dense és a
    rerank az eredeti kérdést kapja), így a "feltölteni" kérdés a "Töltés" fejezetet is megtalálja."""
    s = get_settings()
    strategy = strategy or s.chat_strategy
    model = model or s.embed_model
    top_k = top_k or s.top_k
    min_score = s.rerank_min_score if min_score is None else min_score
    cfg = {"strategy": strategy, "model": model, "top_k": top_k, "dense": use_dense, "bm25": use_bm25,
           "rerank": use_rerank, "min_score": min_score, "keywords": keywords or []}
    timings: dict[str, int] = {}

    with span("retrieve", "RETRIEVER", input=query, **{"metadata": cfg}) as sp:
        lists: list[list[int]] = []
        dense_rank: dict[int, int] = {}
        bm25_rank: dict[int, int] = {}
        if use_dense:
            t0 = time.time()
            vec = llm.embed([query], model=model, purpose="embed_query", message_id=message_id)[0]
            dense = dense_search(vec, strategy, model, s.dense_candidates)
            timings["dense_ms"] = int((time.time() - t0) * 1000)
            lists.append([cid for cid, _ in dense])
            dense_rank = {cid: i + 1 for i, (cid, _) in enumerate(dense)}
        if use_bm25:
            t0 = time.time()
            bm = get_index(strategy).search(" ".join([query, *(keywords or [])]), s.bm25_candidates)
            timings["bm25_ms"] = int((time.time() - t0) * 1000)
            lists.append([cid for cid, _ in bm])
            bm25_rank = {cid: i + 1 for i, (cid, _) in enumerate(bm)}

        fused = rrf_merge(lists, s.rrf_k)
        ordered = sorted(fused, key=fused.get, reverse=True)
        pool_size = s.rerank_candidates if use_rerank else top_k + MAX_IMAGE_HITS * 2   # tartalék a képkorláthoz
        candidates = ordered[:pool_size]
        hits_by_id = load_hits(candidates)
        hits = [hits_by_id[cid] for cid in candidates if cid in hits_by_id]
        for h in hits:
            h.rrf = fused.get(h.chunk_id, 0.0)
            h.dense_rank = dense_rank.get(h.chunk_id)
            h.bm25_rank = bm25_rank.get(h.chunk_id)

        weak: list[Hit] = []
        if use_rerank and hits:
            t0 = time.time()
            with span("rerank", "RERANKER", input=query, **{"reranker.model_name": s.rerank_model}) as rsp:
                scores = llm.rerank(query, [rerank_text(h) for h in hits], message_id=message_id)
                for h, sc in zip(hits, scores):
                    h.rerank_score = sc
                hits.sort(key=lambda h: h.rerank_score or 0.0, reverse=True)
                set_documents(rsp, [{"id": h.chunk_id, "text": h.text, "score": h.rerank_score, "title": h.title,
                                     "page_from": h.page_from} for h in hits[:top_k]], prefix="reranker.output_documents")
            timings["rerank_ms"] = int((time.time() - t0) * 1000)
            good = [h for h in hits if (h.rerank_score or 0) >= min_score]
            if not good:
                weak = hits[:3]
            hits = cap_images(good, top_k)
        else:
            hits = cap_images(hits, top_k)

        set_documents(sp, [{"id": h.chunk_id, "text": h.text, "score": h.rerank_score if h.rerank_score is not None
                            else h.rrf, "title": h.title, "page_from": h.page_from, "section": h.section,
                            "strategy": strategy} for h in hits])
        set_output(sp, {"hits": len(hits), "weak": len(weak), "timings_ms": timings})
    return RetrievalResult(query, hits, weak, timings, cfg)
