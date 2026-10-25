"""Gyors ellenőrzés egy visszajelzésből felvett mérési esetre – az admin „▶ Ellenőrzés most” gombja hívja
(backend: admin_insights.eval_case_check), a teljes mérés (rag_eval.py / prompt_eval.py) helyett, másodpercek alatt.

RAG-eset:    az ÉLES keresés, ahogy a chat futtatja – kérdés-átírás + kulcsszavak, hibrid + rerank + küszöb –,
             és hányadik helyen jön az elvárt útmutató elvárt oldala (relevancia: ugyanaz, mint a rag_eval.py-ban).
             A teljes rag_eval.py ettől kicsit eltérhet: ott a változatok átírás nélkül, küszöb nélkül futnak.
Prompt-eset: a teljes lánc + a két LLM-bíró, pontosan úgy, mint a prompt_eval.py (evaluate_case).
"""

from __future__ import annotations

import time

from common import db

from app.rag.chat import rewrite  # noqa: E402
from app.rag.retrieve import retrieve  # noqa: E402
from prompt_eval import evaluate_case  # noqa: E402
from rag_eval import relevant  # noqa: E402

MIN_CORRECTNESS = 0.8   # prompt-esetnél ennyi kulcselem-lefedettség kell a „✓”-hoz


def _hit(h, i: int | None, doc_id: int, pages: set[int]) -> dict:
    return {"rank": i, "title": h.title, "page_from": h.page_from, "page_to": h.page_to, "section": h.section,
            "kind": h.kind, "score": round(h.rerank_score, 3) if h.rerank_score is not None else None,
            "relevant": relevant(h, doc_id, pages)}


def check_rag(case: dict) -> dict:
    doc = db.fetch_one("SELECT id, title FROM documents WHERE filename = %s", (case["doc_file"],))
    if not doc:
        return {"level": "rag", "ok": False, "error": "Az elvárt útmutató nincs (már) beolvasva."}
    pages = set(case["pages"] or [])
    t0 = time.time()
    plan = rewrite([], case["question"], None)
    res = retrieve(plan["query"], keywords=plan["keywords"])
    hits = [_hit(h, i + 1, doc["id"], pages) for i, h in enumerate(res.hits)]
    rank = next((h["rank"] for h in hits if h["relevant"]), None)
    return {
        "level": "rag", "ok": rank is not None, "rank": rank, "n_hits": len(hits),
        "expected": f"{doc['title']} · {', '.join(map(str, sorted(pages)))}. o.",
        "query": plan["query"], "keywords": plan["keywords"], "hits": hits,
        # ha semmi nem érte el a küszöböt: a legközelebbi jelöltek (ezekből lett volna a válasz)
        "weak": [_hit(h, None, doc["id"], pages) for h in res.weak],
        "ms": int((time.time() - t0) * 1000),
    }


def check_prompt(case: dict) -> dict:
    t0 = time.time()
    row, _, _ = evaluate_case({"id": f"fb{case['id']}", "question": case["question"], "expect": case["expect"],
                               "facts": case["facts"] or []})
    ok = (row["behavior_ok"] and not row["hallucination"]
          and (row["correctness"] is None or row["correctness"] >= MIN_CORRECTNESS) and not row["error"])
    keep = ("behavior", "behavior_ok", "correctness", "context_relevance", "hallucination", "unsupported_claims",
            "citation_ok", "n_sources", "cited", "answer", "judge_explanation", "cost_usd", "error")
    return {"level": "prompt", "ok": bool(ok), "expect": case["expect"], **{k: row[k] for k in keep},
            "ms": int((time.time() - t0) * 1000)}


def check(case: dict) -> dict:
    try:
        return check_rag(case) if case["level"] == "rag" else check_prompt(case)
    except Exception as e:   # az admin a hibát lássa, ne 500-at
        return {"level": case["level"], "ok": False, "error": f"{type(e).__name__}: {e}"}
