"""Egy chat-kérés útja (eseménysor a UI-nak, SSE-ként streamelve):

  1. átírás (LLM, JSON): önálló keresőkérdés + szándék (qa | smalltalk | offtopic) + eszköz
  2. keresés: hibrid (dense + BM25 -> RRF -> rerank), a KÓD hívja, nem az LLM dönt róla
  3. válasz (LLM, stream): csak a forrásokból, [n] hivatkozással; a forrásszöveg <forras> blokkban, ADATKÉNT
  4. mentés: üzenet + források + hivatkozások + tokenek / költség / idők; Phoenix-trace

Események: meta -> plan -> sources -> delta… -> done   (hiba esetén: error)
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Iterator

from psycopg.types.json import Jsonb

from .. import db, llm
from ..config import get_settings
from ..telemetry import current_trace_id, set_output, span
from .retrieve import Hit, retrieve

log = logging.getLogger(__name__)
PROMPTS = Path(__file__).parent / "prompts"
CITE_RE = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)*)\]")

SMALLTALK = (
    "Szia! A használati útmutatókból segítek: kérdezz bátran egy eszköz használatáról, beállításáról, "
    "tisztításáról, karbantartásáról vagy egy hibaüzenetről. A válasz mellett bal oldalt látod, melyik "
    "útmutató melyik oldaláról dolgoztam – onnan meg is nyithatod a PDF-et."
)
OFFTOPIC = ("Ebben nem tudok segíteni – csak a feltöltött használati útmutatókkal kapcsolatos kérdésekre "
            "válaszolok (használat, beállítás, tisztítás, hibaelhárítás).")
NOT_FOUND = "Erről nem találtam információt az útmutatókban."


def load_prompt(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="utf-8")


def devices() -> list[str]:
    return [r["title"] for r in db.fetch_all("SELECT title FROM documents WHERE status = 'indexed' ORDER BY title")]


# ------------------------------------------------------------------ beszélgetés

def ensure_conversation(client_id: str, conversation_id: str | None, first_question: str) -> str:
    if conversation_id:
        row = db.fetch_one("SELECT id FROM conversations WHERE id = %s AND client_id = %s", (conversation_id, client_id))
        if row:
            return str(row["id"])
    cid = str(uuid.uuid4())
    title = first_question.strip().replace("\n", " ")
    db.execute("INSERT INTO conversations (id, client_id, title) VALUES (%s, %s, %s)",
               (cid, client_id, title[:80] + ("…" if len(title) > 80 else "")))
    return cid


def history(conversation_id: str, limit: int) -> list[dict]:
    rows = db.fetch_all(
        """SELECT role, content FROM messages WHERE conversation_id = %s AND content <> '' AND error IS NULL
           ORDER BY created_at DESC LIMIT %s""",
        (conversation_id, limit),
    )
    return [{"role": r["role"], "content": CITE_RE.sub("", r["content"])} for r in reversed(rows)]


# ------------------------------------------------------------------ lépések

def rewrite(hist: list[dict], question: str, message_id: str) -> dict:
    s = get_settings()
    prompt = load_prompt("rewrite.md").format(devices="; ".join(devices()) or "-")
    convo = "\n".join(f"{m['role']}: {m['content'][:600]}" for m in hist[-4:])
    user = f"Előzmények:\n{convo or '(nincs)'}\n\nLegutóbbi üzenet: {question}"
    try:
        raw = llm.chat([{"role": "system", "content": prompt}, {"role": "user", "content": user}],
                       model=s.rewrite_model, purpose="rewrite", json_mode=True, max_tokens=200, temperature=0,
                       message_id=message_id)
        data = json.loads(raw)
        intent = data.get("intent") if data.get("intent") in ("qa", "smalltalk", "offtopic") else "qa"
        keywords = [str(k).strip() for k in (data.get("keywords") or []) if str(k).strip()][:6]
        return {"query": (data.get("query") or question).strip(), "intent": intent, "device": data.get("device"),
                "keywords": keywords}
    except Exception as e:  # az átírás hibája ne akassza meg a választ: az eredeti kérdéssel keresünk
        log.warning("átírás hiba: %s", e)
        return {"query": question, "intent": "qa", "device": None, "keywords": []}


def image_meta(image_ids: list[int]) -> dict[int, dict]:
    if not image_ids:
        return {}
    rows = db.fetch_all("SELECT id, page, caption, description, width, height FROM images WHERE id = ANY(%s)",
                        (image_ids,))
    return {r["id"]: {"id": r["id"], "url": f"/images/{r['id']}", "page": r["page"], "caption": r["caption"],
                      "description": r["description"], "width": r["width"], "height": r["height"]} for r in rows}


def build_sources(hits: list[Hit]) -> list[dict]:
    imgs = image_meta(sorted({i for h in hits for i in h.image_ids}))
    out = []
    for n, h in enumerate(hits, start=1):
        page = h.page_from
        out.append({
            "n": n, "chunk_id": h.chunk_id, "document_id": h.document_id, "title": h.title, "product": h.product,
            "kind": h.kind, "text": h.text, "section": h.section, "page_from": h.page_from, "page_to": h.page_to,
            "pdf_url": f"/files/{h.document_id}.pdf" + (f"#page={page}" if page else ""),
            "images": [imgs[i] for i in h.image_ids if i in imgs],
            "score": h.rerank_score, "dense_rank": h.dense_rank, "bm25_rank": h.bm25_rank,
        })
    return out


def sources_block(sources: list[dict], max_chars: int) -> str:
    parts = []
    for s in sources:
        pages = s["page_from"] if s["page_from"] == s["page_to"] else f"{s['page_from']}–{s['page_to']}"
        attrs = [f'n="{s["n"]}"', f'tipus="{"kép" if s["kind"] == "image" else "szöveg"}"',
                 f'utmutato="{s["title"]}"']
        if s["page_from"]:
            attrs.append(f'oldal="{pages}"')
        if s["section"]:
            attrs.append(f'fejezet="{s["section"]}"')
        parts.append(f"<forras {' '.join(attrs)}>\n{s['text'][:max_chars]}\n</forras>")
    return "\n\n".join(parts)


def cited_numbers(text: str, max_n: int) -> list[int]:
    nums: list[int] = []
    for m in CITE_RE.finditer(text):
        for x in re.split(r"[,;]", m.group(1)):
            v = int(x.strip())
            if 1 <= v <= max_n and v not in nums:
                nums.append(v)
    return nums


def usage_summary(message_id: str) -> dict:
    rows = db.fetch_all(
        """SELECT purpose, model, sum(coalesce(prompt_tokens, 0)) AS prompt_tokens,
                  sum(coalesce(completion_tokens, 0)) AS completion_tokens, sum(coalesce(cost_usd, 0)) AS cost_usd,
                  sum(coalesce(latency_ms, 0)) AS latency_ms, count(*) AS calls
           FROM llm_usage WHERE message_id = %s GROUP BY purpose, model ORDER BY purpose""",
        (message_id,),
    )
    return {
        "prompt_tokens": int(sum(r["prompt_tokens"] for r in rows)),
        "completion_tokens": int(sum(r["completion_tokens"] for r in rows)),
        "cost_usd": float(sum(r["cost_usd"] for r in rows)),
        "by_purpose": [{k: (float(v) if k == "cost_usd" else v) for k, v in r.items()} for r in rows],
    }


def save_assistant(message_id: str, conversation_id: str, content: str, query: str | None, sources: list[dict],
                   cited: list[int], usage: dict, trace_id: str | None, error: str | None = None) -> None:
    db.execute(
        """INSERT INTO messages (id, conversation_id, role, content, search_query, sources, cited, usage, trace_id, error)
           VALUES (%s, %s, 'assistant', %s, %s, %s, %s, %s, %s, %s)""",
        (message_id, conversation_id, content, query, Jsonb(sources), cited, Jsonb(usage), trace_id, error),
    )
    db.execute("UPDATE conversations SET updated_at = now() WHERE id = %s", (conversation_id,))


# ------------------------------------------------------------------ a teljes kérés

def run_chat(client_id: str, conversation_id: str | None, question: str, strategy: str | None = None) -> Iterator[dict]:
    s = get_settings()
    t_start = time.time()
    question = question.strip()
    conv_id = ensure_conversation(client_id, conversation_id, question)
    hist = history(conv_id, s.history_messages)
    user_msg_id, msg_id = str(uuid.uuid4()), str(uuid.uuid4())
    db.execute("INSERT INTO messages (id, conversation_id, role, content) VALUES (%s, %s, 'user', %s)",
               (user_msg_id, conv_id, question))

    with span("chat", "CHAIN", input=question, **{"session.id": conv_id, "user.id": client_id}) as root:
        trace_id = current_trace_id()
        span_id = format(root.get_span_context().span_id, "016x")
        trace_ref = f"{trace_id}:{span_id}" if trace_id else None
        yield {"type": "meta", "conversation_id": conv_id, "message_id": msg_id, "user_message_id": user_msg_id}

        query, sources, answer, cited = None, [], "", []
        timings: dict = {}
        try:
            plan = rewrite(hist, question, msg_id)
            query = plan["query"]
            timings["rewrite_ms"] = int((time.time() - t_start) * 1000)
            yield {"type": "plan", **plan}

            canned = None
            if plan["intent"] == "smalltalk":
                canned = SMALLTALK
            else:
                res = retrieve(query, strategy=strategy, message_id=msg_id, keywords=plan["keywords"])
                timings.update(res.timings_ms)
                if not res.hits:
                    if plan["intent"] == "offtopic":
                        canned = OFFTOPIC
                    else:
                        near = list(dict.fromkeys(h.title for h in res.weak))
                        canned = NOT_FOUND + (f" A kérdéshez legközelebb álló útmutatók: {'; '.join(near)}." if near else "")
                else:
                    sources = build_sources(res.hits)
                    yield {"type": "sources", "sources": sources}

            if canned is not None:
                answer = canned
                timings["ttft_ms"] = int((time.time() - t_start) * 1000)
                yield {"type": "delta", "text": canned}
            else:
                user_content = (f"Források:\n\n{sources_block(sources, s.max_source_chars)}\n\n"
                                f"Kérdés: {question}\n(Önálló keresőkérdés: {query})")
                messages = [{"role": "system", "content": load_prompt("system.md")}, *hist,
                            {"role": "user", "content": user_content}]
                for ev in llm.chat_stream(messages, purpose="chat", message_id=msg_id):
                    if ev["type"] == "delta":
                        if "ttft_ms" not in timings:
                            timings["ttft_ms"] = int((time.time() - t_start) * 1000)
                        answer += ev["text"]
                        yield ev
                    elif ev["type"] == "usage":
                        timings["llm_ttft_ms"] = ev.get("ttft_ms")
                        timings["llm_ms"] = ev.get("latency_ms")
                cited = cited_numbers(answer, len(sources))

            timings["total_ms"] = int((time.time() - t_start) * 1000)
            usage = {**usage_summary(msg_id), **timings, "strategy": strategy or s.chat_strategy,
                     "chat_model": s.chat_model}
            save_assistant(msg_id, conv_id, answer, query, sources, cited, usage, trace_ref)
            root.set_attribute("llm.cost.total", usage["cost_usd"])
            root.set_attribute("metadata", json.dumps({"usage": usage, "cited": cited}, ensure_ascii=False))
            set_output(root, answer)
            yield {"type": "done", "message_id": msg_id, "cited": cited, "usage": usage, "trace_id": trace_id}
        except Exception as e:
            log.exception("chat hiba")
            usage = {**usage_summary(msg_id), **timings, "total_ms": int((time.time() - t_start) * 1000)}
            save_assistant(msg_id, conv_id, answer, query, sources, cited, usage, trace_ref, error=str(e))
            yield {"type": "error", "message": "Hiba történt a válasz készítése közben. Próbáld újra."}
