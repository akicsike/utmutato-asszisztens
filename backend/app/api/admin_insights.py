"""Admin: visszajelzések (lista, statisztika, LLM-es témaelemzés, állapot, mérési esetek), monitoring (token / $ / idők),
mérések."""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Literal
from uuid import UUID

import yaml
from fastapi import APIRouter, Depends, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from .. import db, llm
from ..config import get_settings
from .deps import require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])
PROMPT = Path(__file__).parent.parent / "rag" / "prompts" / "feedback_analysis.md"
EVAL_DIR = os.environ.get("EVAL_DIR", "/eval")

FEEDBACK_SQL = """
SELECT f.rating, f.reasons, f.comment, f.created_at, f.updated_at, f.status, f.admin_note, f.status_at,
       m.id AS message_id, m.content AS answer, m.sources, m.cited, m.conversation_id, m.search_query, m.trace_id,
       (SELECT u.content FROM messages u WHERE u.conversation_id = m.conversation_id AND u.role = 'user'
          AND u.created_at <= m.created_at ORDER BY u.created_at DESC LIMIT 1) AS question,
       (SELECT coalesce(json_agg(json_build_object('id', e.id, 'level', e.level, 'last_check', e.last_check,
                                                   'last_check_at', e.last_check_at) ORDER BY e.id), '[]')
          FROM eval_cases e WHERE e.message_id = m.id) AS eval_cases
FROM feedback f JOIN messages m ON m.id = f.message_id
WHERE (%(rating)s::text IS NULL OR f.rating = %(rating)s)
  AND (%(status)s::text IS NULL OR f.status = %(status)s)
ORDER BY f.updated_at DESC LIMIT %(limit)s
"""
FEEDBACK_STATUSES = ("uj", "vizsgalva", "javitva", "nem_hiba")


def _cited_docs(row: dict) -> list[str]:
    cited = set(row.get("cited") or [])
    return list(dict.fromkeys(s["title"] for s in (row.get("sources") or []) if s.get("n") in cited))


def _slim_sources(row: dict) -> list[dict]:
    """A válasz forrásai a hibakereséshez: útmutató, oldal, rerank-pont, hivatkozott-e (a teljes szöveg nélkül)."""
    cited = set(row.get("cited") or [])
    return [{"n": s.get("n"), "title": s.get("title"), "document_id": s.get("document_id"), "kind": s.get("kind"),
             "section": s.get("section"), "page_from": s.get("page_from"), "page_to": s.get("page_to"),
             "score": s.get("score"), "cited": s.get("n") in cited, "pdf_url": s.get("pdf_url")}
            for s in (row.get("sources") or [])]


def _trace_url(trace_ref: str | None) -> str | None:
    """A Phoenix a /redirects/traces/<trace_id> címről a trace oldalára irányít (a projekt-azonosító nem kell)."""
    s = get_settings()
    if not trace_ref or not s.phoenix_endpoint:
        return None
    return f"{s.phoenix_ui_url.rstrip('/')}/redirects/traces/{trace_ref.split(':', 1)[0]}"


@router.get("/feedback")
def feedback_list(rating: str | None = None, status: str | None = None, limit: int = 200) -> dict:
    rows = db.fetch_all(FEEDBACK_SQL, {"rating": rating if rating in ("up", "down") else None,
                                       "status": status if status in FEEDBACK_STATUSES else None, "limit": min(limit, 1000)})
    items = [{k: v for k, v in r.items() if k not in ("sources", "cited", "trace_id")}
             | {"documents": _cited_docs(r), "sources": _slim_sources(r), "trace_url": _trace_url(r["trace_id"])}
             for r in rows]
    all_rows = db.fetch_all(FEEDBACK_SQL, {"rating": None, "status": None, "limit": 100000})
    up = sum(r["rating"] == "up" for r in all_rows)
    down = len(all_rows) - up
    answers = db.fetch_one("SELECT count(*) AS n FROM messages WHERE role = 'assistant' AND error IS NULL")["n"]
    by_doc: Counter = Counter()
    for r in all_rows:
        if r["rating"] == "down":
            by_doc.update(_cited_docs(r) or ["(nincs hivatkozott útmutató)"])
    return {
        "items": items,
        "stats": {
            "answers": answers, "rated": len(all_rows), "up": up, "down": down,
            "satisfaction": round(up / len(all_rows), 3) if all_rows else None,
            "rated_share": round(len(all_rows) / answers, 3) if answers else None,
            "reasons": Counter(x for r in all_rows for x in (r["reasons"] or [])).most_common(),
            "down_by_document": by_doc.most_common(15),
            # a 👎-ok állapota (a 👍-nál nincs teendő)
            "down_by_status": {st: sum(1 for r in all_rows if r["rating"] == "down" and r["status"] == st)
                               for st in FEEDBACK_STATUSES},
        },
        "rerank_min_score": get_settings().rerank_min_score,
        "latest_analysis": db.fetch_one("SELECT * FROM feedback_analyses ORDER BY id DESC LIMIT 1"),
    }


class FeedbackPatch(BaseModel):
    status: Literal["uj", "vizsgalva", "javitva", "nem_hiba"] | None = None
    admin_note: str | None = None


@router.patch("/feedback/{message_id}")
def feedback_patch(message_id: UUID, body: FeedbackPatch) -> dict:
    """Az admin állapota és megjegyzése egy visszajelzésen (új / vizsgálva / javítva / nem hiba)."""
    row = db.fetch_one(
        """UPDATE feedback SET status = coalesce(%(status)s, status),
               status_at = CASE WHEN %(status)s::text IS NULL THEN status_at ELSE now() END,
               admin_note = CASE WHEN %(note_set)s THEN nullif(btrim(%(note)s), '') ELSE admin_note END
           WHERE message_id = %(id)s RETURNING status, admin_note, status_at""",
        {"status": body.status, "note_set": body.admin_note is not None, "note": body.admin_note or "", "id": message_id},
    )
    if not row:
        raise HTTPException(404, "nincs ilyen visszajelzés")
    return row


# ----------------------------------------------------------------- mérési esetek visszajelzésből
class EvalCaseIn(BaseModel):
    message_id: UUID | None = None
    level: Literal["rag", "prompt"]
    question: str = Field(min_length=3, max_length=1000)
    doc_file: str | None = None
    pages: list[int] | None = None
    expect: Literal["answer", "not_found", "refuse", "clarify"] | None = None
    facts: list[str] | None = None


def _case_yaml(rows: list[dict], level: str) -> str:
    """A YAML-kérdéssor formátumában (eval/datasets/rag_questions.yaml, prompt_cases.yaml) – a végleges felvételhez."""
    items = []
    for r in rows:
        if r["level"] != level:
            continue
        if level == "rag":
            items.append({"id": f"fb{r['id']}", "question": r["question"], "doc": r["doc_file"], "pages": r["pages"],
                          "keywords": []})
        else:
            items.append({"id": f"fb{r['id']}", "question": r["question"], "expect": r["expect"], "facts": r["facts"] or []})
    return yaml.safe_dump(items, allow_unicode=True, sort_keys=False, default_flow_style=None, width=1000) if items else ""


@router.get("/eval-cases")
def eval_cases_list() -> dict:
    rows = db.fetch_all(
        """SELECT e.*, d.title AS doc_title FROM eval_cases e
           LEFT JOIN documents d ON d.filename = e.doc_file ORDER BY e.id DESC""")
    return {"items": rows, "yaml": {"rag": _case_yaml(rows[::-1], "rag"), "prompt": _case_yaml(rows[::-1], "prompt")}}


@router.post("/eval-cases")
def eval_cases_create(body: EvalCaseIn) -> dict:
    if body.level == "rag":
        if not body.doc_file or not body.pages:
            raise HTTPException(400, "RAG-esetnél add meg az elvárt útmutatót és legalább egy oldalt.")
        if not db.fetch_one("SELECT 1 FROM documents WHERE filename = %s", (body.doc_file,)):
            raise HTTPException(400, "Nincs ilyen útmutató.")
        if any(p < 1 for p in body.pages):
            raise HTTPException(400, "Az oldalszám 1-től kezdődik.")
    else:
        if not body.expect:
            raise HTTPException(400, "Prompt-esetnél add meg az elvárt viselkedést.")
        if body.expect == "answer" and not [f for f in body.facts or [] if f.strip()]:
            raise HTTPException(400, "Válaszolós esetnél add meg a helyes válasz legalább egy kulcselemét.")
    return db.fetch_one(
        """INSERT INTO eval_cases (message_id, level, question, doc_file, pages, expect, facts)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *""",
        (body.message_id, body.level, body.question.strip(),
         body.doc_file if body.level == "rag" else None, sorted(set(body.pages or [])) if body.level == "rag" else None,
         body.expect if body.level == "prompt" else None,
         [f.strip() for f in body.facts or [] if f.strip()] if body.level == "prompt" else None),
    )


@router.delete("/eval-cases/{case_id}")
def eval_cases_delete(case_id: int) -> dict:
    db.execute("DELETE FROM eval_cases WHERE id = %s", (case_id,))
    return {"ok": True}


def _quick_check():
    """Az eval/quick_check.py – a mérőkód a /eval kötetről (docker-compose: ./eval:/eval), nem az image-ből."""
    if EVAL_DIR not in sys.path:
        sys.path.insert(0, EVAL_DIR)
    try:
        import quick_check  # type: ignore[import-not-found]
    except ImportError as e:
        raise HTTPException(503, f"A mérőkód nem érhető el ({EVAL_DIR}): {e}") from e
    return quick_check


@router.post("/eval-cases/{case_id}/check")
def eval_case_check(case_id: int) -> dict:
    """„▶ Ellenőrzés most”: egyetlen eset gyors ellenőrzése (RAG: éles keresés, prompt: lánc + LLM-bíró).
    Az eredmény az esethez mentődik (last_check), a teljes mérés ettől független."""
    case = db.fetch_one("SELECT * FROM eval_cases WHERE id = %s", (case_id,))
    if not case:
        raise HTTPException(404, "nincs ilyen mérési eset")
    result = _quick_check().check(case)
    row = db.fetch_one("UPDATE eval_cases SET last_check = %s, last_check_at = now() WHERE id = %s RETURNING last_check_at",
                       (Jsonb(result), case_id))
    return {"id": case_id, "last_check": result, "last_check_at": row["last_check_at"]}


@router.post("/feedback/analyze")
def feedback_analyze() -> dict:
    rows = db.fetch_all(FEEDBACK_SQL, {"rating": "down", "status": None, "limit": 200})
    if not rows:
        raise HTTPException(400, "Még nincs negatív visszajelzés.")
    items = [{"kerdes": r["question"], "valasz": (r["answer"] or "")[:400], "okok": r["reasons"],
              "megjegyzes": r["comment"], "utmutatok": _cited_docs(r)} for r in rows]
    s = get_settings()
    raw = llm.chat([{"role": "system", "content": PROMPT.read_text(encoding="utf-8")},
                    {"role": "user", "content": json.dumps(items, ensure_ascii=False)}],
                   model=s.judge_model, purpose="feedback_analysis", json_mode=True, max_tokens=1500, temperature=0.2)
    result = json.loads(raw)
    return db.fetch_one("INSERT INTO feedback_analyses (model, n_feedback, result) VALUES (%s, %s, %s) RETURNING *",
                        (s.judge_model, len(rows), Jsonb(result)))


@router.get("/monitoring")
def monitoring(days: int = 7) -> dict:
    p = {"d": max(1, min(days, 365))}
    since = "created_at > now() - make_interval(days => %(d)s)"
    by_purpose = db.fetch_all(
        f"""SELECT purpose, model, count(*) AS calls, sum(coalesce(prompt_tokens,0)) AS prompt_tokens,
                   sum(coalesce(completion_tokens,0)) AS completion_tokens, sum(coalesce(cost_usd,0)) AS cost_usd,
                   avg(latency_ms)::int AS avg_latency_ms, count(*) FILTER (WHERE NOT ok) AS errors
            FROM llm_usage WHERE {since} GROUP BY purpose, model ORDER BY cost_usd DESC""", p)
    by_day = db.fetch_all(
        f"""SELECT date_trunc('day', created_at)::date AS day,
                   sum(coalesce(cost_usd,0)) FILTER (WHERE document_id IS NULL) AS chat_cost,
                   sum(coalesce(cost_usd,0)) FILTER (WHERE document_id IS NOT NULL) AS ingest_cost,
                   sum(coalesce(total_tokens,0)) AS tokens
            FROM llm_usage WHERE {since} GROUP BY 1 ORDER BY 1""", p)
    latency = db.fetch_one(
        f"""SELECT count(*) AS answers, count(*) FILTER (WHERE error IS NOT NULL) AS errors,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY (usage->>'ttft_ms')::float) AS ttft_p50,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY (usage->>'ttft_ms')::float) AS ttft_p95,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY (usage->>'total_ms')::float) AS total_p50,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY (usage->>'total_ms')::float) AS total_p95,
                   avg((usage->>'cost_usd')::float) AS avg_cost
            FROM messages WHERE role = 'assistant' AND usage IS NOT NULL AND {since}""", p)
    recent = db.fetch_all(
        """SELECT m.id, m.created_at, m.usage, m.error, f.rating,
                  (SELECT u.content FROM messages u WHERE u.conversation_id = m.conversation_id AND u.role = 'user'
                     AND u.created_at <= m.created_at ORDER BY u.created_at DESC LIMIT 1) AS question
           FROM messages m LEFT JOIN feedback f ON f.message_id = m.id
           WHERE m.role = 'assistant' ORDER BY m.created_at DESC LIMIT 30""")
    s = get_settings()
    return {"days": p["d"], "by_purpose": by_purpose, "by_day": by_day, "latency": latency, "recent": recent,
            "phoenix_url": s.phoenix_ui_url if s.phoenix_endpoint else None}


COST_GROUP_SQL = """CASE
    WHEN purpose IN ('chat') THEN 'valasz'
    WHEN purpose IN ('rewrite') THEN 'atiras'
    WHEN purpose IN ('embed_query', 'rerank') THEN 'kereses'
    WHEN purpose IN ('vlm', 'embed', 'metadata') THEN 'beolvasas'
    ELSE 'meres' END"""


@router.get("/analytics")
def analytics(days: int = 30, include_eval: bool = True) -> dict:
    """Az Analitika fül adatai: forgalom és kimenet, elégedettség, latencia lépésenként és eloszlásban,
    útmutatónkénti kérdések, rerank-biztonság, költség célcsoportonként, megválaszolatlan kérdések."""
    p = {"d": max(1, min(days, 365))}
    eval_filter = "" if include_eval else "AND c.client_id NOT LIKE 'eval-%%' AND c.client_id NOT LIKE 'smoke-%%'"
    rows = db.fetch_all(
        f"""SELECT m.id, m.created_at::date AS day, m.content, m.sources, m.cited, m.usage, m.error,
                   f.rating,
                   (SELECT u.content FROM messages u WHERE u.conversation_id = m.conversation_id AND u.role = 'user'
                      AND u.created_at <= m.created_at ORDER BY u.created_at DESC LIMIT 1) AS question
            FROM messages m JOIN conversations c ON c.id = m.conversation_id
            LEFT JOIN feedback f ON f.message_id = m.id
            WHERE m.role = 'assistant' AND m.created_at > now() - make_interval(days => %(d)s) {eval_filter}
            ORDER BY m.created_at""", p)

    def outcome(r: dict) -> str:
        if r["error"]:
            return "hiba"
        if (r["content"] or "").startswith("Erről nem találtam"):
            return "nem_talalta"
        return "valaszolt" if r["sources"] else "egyeb"

    daily: dict[str, dict] = {}
    by_doc: dict[str, dict] = {}
    lat_hist = [0] * 9          # teljes válaszidő: 0-1, 1-2, ... 7-8, 8+ s
    score_hist = [0] * 10       # a legjobb forrás rerank-pontja: 0,0-0,1 … 0,9-1,0
    unanswered = []
    for r in rows:
        d = str(r["day"])
        o = outcome(r)
        u = r["usage"] or {}
        day = daily.setdefault(d, {"day": d, "valaszolt": 0, "nem_talalta": 0, "egyeb": 0, "hiba": 0, "up": 0, "down": 0,
                                   "_lat": []})
        day[o] += 1
        if r["rating"] in ("up", "down"):
            day[r["rating"]] += 1
        if o == "valaszolt" and u.get("total_ms"):
            day["_lat"].append(u)
            lat_hist[min(8, int(u["total_ms"] // 1000))] += 1
        if o == "nem_talalta":
            unanswered.append({"day": d, "question": r["question"]})
        srcs = r["sources"] or []
        scores = [s.get("score") for s in srcs if s.get("score") is not None]
        if scores:
            score_hist[min(9, int(max(scores) * 10))] += 1
        cited = set(r["cited"] or [])
        for title in dict.fromkeys(s["title"] for s in srcs if s.get("n") in cited):
            e = by_doc.setdefault(title, {"title": title, "kerdes": 0, "up": 0, "down": 0})
            e["kerdes"] += 1
            if r["rating"] in ("up", "down"):
                e[r["rating"]] += 1

    def avg(xs: list[dict], key: str) -> float:
        vals = [x.get(key) or 0 for x in xs]
        return round(sum(vals) / len(vals)) if vals else 0

    traffic, satisfaction, latency = [], [], []
    for d in sorted(daily):
        x = daily[d]
        traffic.append({k: x[k] for k in ("day", "valaszolt", "nem_talalta", "egyeb", "hiba")})
        rated = x["up"] + x["down"]
        satisfaction.append({"day": d, "rate": round(x["up"] / rated, 3) if rated else None, "up": x["up"], "down": x["down"]})
        lat = x["_lat"]
        if lat:
            search = [{"v": (u.get("dense_ms") or 0) + (u.get("bm25_ms") or 0)} for u in lat]
            latency.append({"day": d, "n": len(lat), "atiras": avg(lat, "rewrite_ms"), "kereses": avg(search, "v"),
                            "rerank": avg(lat, "rerank_ms"), "valasz": avg(lat, "llm_ms")})

    cost = db.fetch_all(
        f"""SELECT created_at::date AS day, {COST_GROUP_SQL} AS grp, sum(coalesce(cost_usd, 0)) AS usd
            FROM llm_usage WHERE created_at > now() - make_interval(days => %(d)s) GROUP BY 1, 2 ORDER BY 1""", p)
    cost_daily: dict[str, dict] = {}
    for c in cost:
        e = cost_daily.setdefault(str(c["day"]), {"day": str(c["day"]), "valasz": 0.0, "atiras": 0.0, "kereses": 0.0,
                                                   "beolvasas": 0.0, "meres": 0.0})
        e[c["grp"]] = round(float(c["usd"]), 5)

    totals = {
        "valaszok": len(rows),
        "nem_talalta_arany": round(sum(1 for r in rows if outcome(r) == "nem_talalta") / len(rows), 3) if rows else None,
        "ertekelt": sum(1 for r in rows if r["rating"]),
        "elegedettseg": (round(sum(1 for r in rows if r["rating"] == "up") / max(1, sum(1 for r in rows if r["rating"])), 3)
                         if any(r["rating"] for r in rows) else None),
    }
    return {
        "days": p["d"], "include_eval": include_eval, "totals": totals,
        "traffic": traffic, "satisfaction": satisfaction, "latency": latency,
        "latency_hist": [{"bucket": f"{i}–{i + 1} s" if i < 8 else "8+ s", "n": n} for i, n in enumerate(lat_hist)],
        "score_hist": [{"bucket": f"{i / 10:.1f}–{(i + 1) / 10:.1f}".replace(".", ","), "n": n} for i, n in enumerate(score_hist)],
        "documents": sorted(by_doc.values(), key=lambda e: e["kerdes"], reverse=True)[:12],
        "cost": [cost_daily[d] for d in sorted(cost_daily)],
        "unanswered": unanswered[-15:][::-1],
        "rerank_min_score": get_settings().rerank_min_score,
    }


@router.get("/analytics/score-bucket")
def analytics_score_bucket(bucket: int, days: int = 30, include_eval: bool = True) -> dict:
    """A „Keresési biztonság” diagram egy oszlopa (a legjobb forrás rerank-pontja bucket/10 … (bucket+1)/10):
    mely válaszok tartoznak ide – kérdés, keresőkérdés, legjobb forrás, kimenet, értékelés, Phoenix-link, mérési esetek."""
    if not 0 <= bucket <= 9:
        raise HTTPException(400, "a bucket 0–9 lehet")
    p = {"d": max(1, min(days, 365))}
    eval_filter = "" if include_eval else "AND c.client_id NOT LIKE 'eval-%%' AND c.client_id NOT LIKE 'smoke-%%'"
    rows = db.fetch_all(
        f"""SELECT m.id AS message_id, m.created_at, m.content, m.sources, m.cited, m.search_query, m.trace_id, m.error,
                   c.client_id, f.rating, f.reasons, f.comment,
                   (SELECT u.content FROM messages u WHERE u.conversation_id = m.conversation_id AND u.role = 'user'
                      AND u.created_at <= m.created_at ORDER BY u.created_at DESC LIMIT 1) AS question,
                   (SELECT coalesce(json_agg(json_build_object('id', e.id, 'level', e.level, 'last_check', e.last_check,
                                                               'last_check_at', e.last_check_at) ORDER BY e.id), '[]')
                      FROM eval_cases e WHERE e.message_id = m.id) AS eval_cases
            FROM messages m JOIN conversations c ON c.id = m.conversation_id
            LEFT JOIN feedback f ON f.message_id = m.id
            WHERE m.role = 'assistant' AND m.sources IS NOT NULL
              AND m.created_at > now() - make_interval(days => %(d)s) {eval_filter}
            ORDER BY m.created_at DESC""", p)
    items = []
    for r in rows:
        srcs = [s for s in (r["sources"] or []) if s.get("score") is not None]
        if not srcs:
            continue
        best = max(srcs, key=lambda s: s["score"])
        # ugyanaz a sávolás, mint az analytics() score_hist-jében
        if min(9, int(best["score"] * 10)) != bucket:
            continue
        cited = set(r["cited"] or [])
        items.append({
            "message_id": r["message_id"], "created_at": r["created_at"], "question": r["question"],
            "search_query": r["search_query"], "answer": r["content"], "top_score": best["score"],
            "best_source": {k: best.get(k) for k in ("title", "document_id", "page_from", "page_to", "section", "pdf_url")},
            "n_sources": len(r["sources"] or []), "cited_best": best.get("n") in cited,
            "rating": r["rating"], "reasons": r["reasons"] or [], "comment": r["comment"], "error": r["error"],
            "test_traffic": r["client_id"].startswith(("eval-", "smoke-")),
            "trace_url": _trace_url(r["trace_id"]), "eval_cases": r["eval_cases"],
        })
    items.sort(key=lambda x: x["top_score"])
    return {"bucket": bucket, "range": [bucket / 10, (bucket + 1) / 10], "n": len(items), "items": items[:200]}


@router.get("/eval-runs")
def eval_runs() -> dict:
    return {"runs": db.fetch_all("SELECT id, level, name, config, summary, created_at FROM eval_runs ORDER BY id DESC")}


@router.get("/eval-runs/{run_id}")
def eval_run(run_id: int) -> dict:
    row = db.fetch_one("SELECT * FROM eval_runs WHERE id = %s", (run_id,))
    if not row:
        raise HTTPException(404, "nincs ilyen mérés")
    return row
