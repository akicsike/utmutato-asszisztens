"""1. szint – RAG-mérés: Precision@k, Recall@k, Hit@k, MRR a 30 kérdéses, kézzel ellenőrzött kérdéssoron.

Összevetések (mind ugyanazon a kérdéssoron, k = TOP_K):
  A) keresési módszer: csak dense · csak BM25 · hibrid (RRF) · hibrid + rerank   [hybrid chunkolás, bge-m3]
  B) chunkolás: szerkezet szerinti (hybrid) vs fix tokenablak (fixed)             [dense és hibrid + rerank]
  C) embedding-modell: EVAL_EMBED_MODELS                                           [dense és hibrid + rerank]
  +  éles konfiguráció: hibrid + rerank + relevancia-küszöb (RERANK_MIN_SCORE) – a precision itt a ténylegesen
     visszaadott (kevesebb) találaton számolódik.

Relevancia: a chunk az elvárt útmutatóból jön ÉS oldaltartománya metszi az elvárt oldalakat.
Recall: az elvárt oldalak hány százalékát fedik le a releváns találatok.
A kérdéssor mellé az adminon visszajelzésből felvett esetek is bekerülnek (eval_cases tábla, „fb<id>” azonosító).
Futtatás: docker compose exec api python /eval/rag_eval.py
"""

from __future__ import annotations

import time

from common import db, feedback_cases, get_settings, load_yaml, mean, save_run, setup, flush_traces

from app.rag.chat import rewrite  # noqa: E402
from app.rag.retrieve import retrieve  # noqa: E402


def relevant(hit, doc_id: int, pages: set[int]) -> bool:
    if hit.document_id != doc_id or not hit.page_from:
        return False
    return bool(set(range(hit.page_from, (hit.page_to or hit.page_from) + 1)) & pages)


def score(hits, doc_id: int, pages: set[int], k: int) -> dict:
    hits = hits[:k]
    rel = [relevant(h, doc_id, pages) for h in hits]
    covered: set[int] = set()
    for h, r in zip(hits, rel):
        if r:
            covered |= set(range(h.page_from, (h.page_to or h.page_from) + 1)) & pages
    first = next((i + 1 for i, r in enumerate(rel) if r), None)
    return {
        "precision": sum(rel) / len(hits) if hits else 0.0,
        "recall": len(covered) / len(pages),
        "hit": 1.0 if first else 0.0,
        "rr": 1.0 / first if first else 0.0,
        "rank": first,
        "doc_hit": 1.0 if any(h.document_id == doc_id for h in hits) else 0.0,
        "n": len(hits),
    }


def variants(s) -> list[dict]:
    base = s.embed_model
    out = [
        {"name": "dense", "group": "A keresési módszer", "strategy": "hybrid", "model": base, "dense": True, "bm25": False, "rerank": False},
        {"name": "bm25", "group": "A keresési módszer", "strategy": "hybrid", "model": base, "dense": False, "bm25": True, "rerank": False},
        {"name": "hibrid (RRF)", "group": "A keresési módszer", "strategy": "hybrid", "model": base, "dense": True, "bm25": True, "rerank": False},
        {"name": "hibrid + rerank", "group": "A keresési módszer", "strategy": "hybrid", "model": base, "dense": True, "bm25": True, "rerank": True},
        {"name": "hibrid + rerank + kulcsszavak", "group": "A keresési módszer", "strategy": "hybrid", "model": base, "dense": True, "bm25": True, "rerank": True, "keywords": True},
        {"name": "fixed · dense", "group": "B chunkolás", "strategy": "fixed", "model": base, "dense": True, "bm25": False, "rerank": False},
        {"name": "fixed · hibrid + rerank", "group": "B chunkolás", "strategy": "fixed", "model": base, "dense": True, "bm25": True, "rerank": True},
    ]
    for m in s.eval_embed_model_list:
        if m == base:
            continue
        short = m.split("/")[-1]
        out.append({"name": f"{short} · dense", "group": "C embedding", "strategy": "hybrid", "model": m, "dense": True, "bm25": False, "rerank": False})
        out.append({"name": f"{short} · hibrid + rerank", "group": "C embedding", "strategy": "hybrid", "model": m, "dense": True, "bm25": True, "rerank": True})
    return out


def model_ready(model: str, strategy: str) -> bool:
    row = db.fetch_one(
        """SELECT count(*) FILTER (WHERE e.chunk_id IS NULL) AS missing, count(*) AS n FROM chunks c
           LEFT JOIN embeddings e ON e.chunk_id = c.id AND e.model = %s WHERE c.strategy = %s""", (model, strategy))
    return row["n"] > 0 and row["missing"] == 0


def main() -> None:
    setup()
    s = get_settings()
    k = s.top_k
    fb = feedback_cases("rag")
    items = load_yaml("rag_questions.yaml") + fb
    docs = {r["filename"]: r["id"] for r in db.fetch_all("SELECT id, filename FROM documents")}
    vs = [v for v in variants(s) if not v["dense"] or model_ready(v["model"], v["strategy"])]
    skipped = [v["name"] for v in variants(s) if v not in vs]
    if skipped:
        print("kihagyva (nincs teljes embedding – futtasd: python /eval/embed_models.py):", skipped)

    per_variant: dict[str, list[dict]] = {v["name"]: [] for v in vs}
    per_variant["éles: hibrid + rerank + küszöb"] = []
    timings: dict[str, list[int]] = {v["name"]: [] for v in vs}
    results = []
    for it in items:
        doc_id = docs.get(it["doc"])
        if doc_id is None:
            print(f"{it['id']}: hiányzó dokumentum {it['doc']} – kihagyva")
            continue
        pages = set(it["pages"])
        row = {"id": it["id"], "question": it["question"], "doc": it["doc"], "pages": ",".join(map(str, it["pages"]))}
        keywords = rewrite([], it["question"], None)["keywords"] if any(v.get("keywords") for v in vs) else []
        row["keywords"] = ", ".join(keywords)
        for v in vs:
            t0 = time.time()
            res = retrieve(it["question"], strategy=v["strategy"], model=v["model"], top_k=k, use_dense=v["dense"],
                           use_bm25=v["bm25"], use_rerank=v["rerank"], min_score=0.0,
                           keywords=keywords if v.get("keywords") else None)
            timings[v["name"]].append(int((time.time() - t0) * 1000))
            sc = score(res.hits, doc_id, pages, k)
            per_variant[v["name"]].append(sc)
            row[f"rank · {v['name']}"] = sc["rank"]
            if v["name"] == "hibrid + rerank":
                kept = [h for h in res.hits if (h.rerank_score or 0) >= s.rerank_min_score]
                live = score(kept, doc_id, pages, k) if kept else {"precision": 0.0, "recall": 0.0, "hit": 0.0, "rr": 0.0, "rank": None, "doc_hit": 0.0, "n": 0}
                per_variant["éles: hibrid + rerank + küszöb"].append(live)
                row["éles · találat"] = live["n"]
                row["top1"] = f"{res.hits[0].title[:40]} p{res.hits[0].page_from}" if res.hits else None
        results.append(row)
        print(f"{it['id']}: " + "  ".join(f"{name.split(' ')[0]}={row.get(f'rank · {name}')}" for name in list(per_variant)[:4]))

    groups = {v["name"]: v["group"] for v in vs}
    groups["éles: hibrid + rerank + küszöb"] = "A keresési módszer"
    table = []
    for name, scores in per_variant.items():
        table.append({
            "csoport": groups[name], "változat": name,
            f"precision@{k}": mean(x["precision"] for x in scores),
            f"recall@{k}": mean(x["recall"] for x in scores),
            f"hit@{k}": mean(x["hit"] for x in scores),
            "MRR": mean(x["rr"] for x in scores),
            "útmutató-találat": mean(x["doc_hit"] for x in scores),
            "átl. találat": mean(x["n"] for x in scores),
            "átl. idő ms": mean(timings.get(name, [])) if name in timings else None,
        })
    for r in table:
        print(f"{r['csoport']:<22} {r['változat']:<36} P={r[f'precision@{k}']} R={r[f'recall@{k}']} "
              f"Hit={r[f'hit@{k}']} MRR={r['MRR']}")
    main_row = next(r for r in table if r["változat"] == "hibrid + rerank")
    summary = {
        "metrics": {"kérdés": len(results), f"precision@{k}": main_row[f"precision@{k}"], f"recall@{k}": main_row[f"recall@{k}"],
                    f"hit@{k}": main_row[f"hit@{k}"], "MRR": main_row["MRR"]},
        "table": table,
        "notes": "Fő konfiguráció: szerkezet szerinti (hybrid) chunkolás, bge-m3, BM25 + dense -> RRF -> Cohere rerank. "
                 "Relevancia: elvárt útmutató + elvárt oldal(ak) metszete."
                 + (f" Ebből {len(fb)} kérdés visszajelzésből (fb…)." if fb else ""),
    }
    config = {"top_k": k, "rrf_k": s.rrf_k, "dense_candidates": s.dense_candidates, "bm25_candidates": s.bm25_candidates,
              "rerank_candidates": s.rerank_candidates, "rerank_model": s.rerank_model, "rerank_min_score": s.rerank_min_score,
              "variants": [v["name"] for v in vs]}
    save_run("rag", f"RAG – {len(results)} kérdés, {len(vs)} változat", config, summary, results)
    flush_traces()


if __name__ == "__main__":
    main()
