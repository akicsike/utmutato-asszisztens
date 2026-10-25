"""Valódi BM25 (Okapi) a chunkok embed_text-jén, stratégiánként a memóriában.

score(q, d) = Σ_t  idf(t) · tf(t,d)·(k1+1) / (tf(t,d) + k1·(1 − b + b·|d|/avgdl))
idf(t)      = ln(1 + (N − df(t) + 0.5) / (df(t) + 0.5))

Miért nem a Postgres ts_rank? Az nem BM25: nem telítődik a szógyakoriság (tf), és nem normál a
dokumentumhosszra úgy, mint a BM25. ~5000 chunknál a teljes index a memóriában is elfér (pár MB, <1 s
felépítés), így minden chunk pontozható jelölt-szűrés nélkül. Az index_state.version jelzi, ha az
indexelés változott – akkor a következő kereséskor újraépül.
"""

from __future__ import annotations

import logging
import math
import threading
from collections import Counter, defaultdict

from .. import db
from .tokenizer import tokenize

log = logging.getLogger(__name__)


class BM25Index:
    def __init__(self, ids: list[int], texts: list[str], k1: float = 1.2, b: float = 0.75):
        self.ids = ids
        self.k1, self.b = k1, b
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.lengths: list[int] = []
        for i, text in enumerate(texts):
            tf = Counter(tokenize(text))
            self.lengths.append(sum(tf.values()))
            for term, n in tf.items():
                self.postings[term].append((i, n))
        self.n = len(ids)
        self.avgdl = (sum(self.lengths) / self.n) if self.n else 1.0
        self.idf = {t: math.log(1 + (self.n - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self.postings.items()}

    def search(self, query: str, top_n: int) -> list[tuple[int, float]]:
        scores: dict[int, float] = defaultdict(float)
        for term in set(tokenize(query)):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, tf in self.postings[term]:
                norm = self.k1 * (1 - self.b + self.b * self.lengths[i] / self.avgdl)
                scores[i] += idf * tf * (self.k1 + 1) / (tf + norm)
        best = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_n]
        return [(self.ids[i], s) for i, s in best]


_cache: dict[str, tuple[int, BM25Index]] = {}
_lock = threading.Lock()


def get_index(strategy: str) -> BM25Index:
    row = db.fetch_one("SELECT version FROM index_state WHERE strategy = %s", (strategy,))
    version = row["version"] if row else 0
    with _lock:
        cached = _cache.get(strategy)
        if cached and cached[0] == version:
            return cached[1]
        rows = db.fetch_all("SELECT id, embed_text FROM chunks WHERE strategy = %s ORDER BY id", (strategy,))
        index = BM25Index([r["id"] for r in rows], [r["embed_text"] for r in rows])
        _cache[strategy] = (version, index)
        log.info("BM25-index felépítve: %s (%s chunk, verzió %s)", strategy, index.n, version)
        return index
