"""Chat (SSE), beszélgetések és visszajelzés.

A felhasználót a böngésző azonosítja (X-Client-Id fejléc, a UI localStorage-ban tartott UUID-ja) – a
beszélgetések ehhez kötődnek, más böngésző nem töltheti be őket.
"""

from __future__ import annotations

import json
import logging
import re
import threading

import httpx
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import db
from ..config import get_settings
from ..rag.chat import devices, run_chat

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])
CLIENT_RE = re.compile(r"^[A-Za-z0-9\-]{8,64}$")

FEEDBACK_REASONS = [
    {"code": "teves", "label": "Téves"},
    {"code": "nem_talalta", "label": "Nem találta"},
    {"code": "hianyos", "label": "Hiányos"},
    {"code": "rossz_forras", "label": "Rossz forrás"},
    {"code": "rossz_kep", "label": "Rossz kép"},
    {"code": "nehezen_ertheto", "label": "Nehezen érthető"},
]
REASON_CODES = {r["code"] for r in FEEDBACK_REASONS}

EXAMPLES = [
    "Hogyan kell vízkőteleníteni a JURA Impressa S9 kávégépet?",
    "Hogyan tisztítsam a mosogatógép szűrőjét?",
    "Hogyan párosítsam a hordozható lemezjátszót Bluetooth-on?",
    "Mit tegyek, ha a 3D nyomtató nem tapad az asztalra?",
]


def client_id(x_client_id: str = Header(default="")) -> str:
    if not CLIENT_RE.match(x_client_id or ""):
        raise HTTPException(400, "Hiányzó vagy hibás X-Client-Id fejléc")
    return x_client_id


def own_conversation(conversation_id: str, cid: str) -> dict:
    row = db.fetch_one("SELECT * FROM conversations WHERE id = %s AND client_id = %s", (conversation_id, cid))
    if not row:
        raise HTTPException(404, "nincs ilyen beszélgetés")
    return row


# ------------------------------------------------------------------ chat

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = None
    strategy: str | None = None


@router.post("/chat")
def chat(req: ChatRequest, x_client_id: str = Header(default="")) -> StreamingResponse:
    cid = client_id(x_client_id)
    s = get_settings()
    strategy = req.strategy if req.strategy in s.strategy_list else None

    def sse():
        for event in run_chat(cid, req.conversation_id, req.message, strategy):
            yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/config")
def config() -> dict:
    s = get_settings()
    return {"examples": EXAMPLES, "devices": devices(), "feedback_reasons": FEEDBACK_REASONS,
            "strategies": s.strategy_list, "default_strategy": s.chat_strategy, "chat_model": s.chat_model}


# ------------------------------------------------------------------ beszélgetések

@router.get("/conversations")
def list_conversations(x_client_id: str = Header(default="")) -> dict:
    cid = client_id(x_client_id)
    rows = db.fetch_all(
        """SELECT c.id, c.title, c.created_at, c.updated_at,
                  (SELECT count(*) FROM messages m WHERE m.conversation_id = c.id) AS n_messages
           FROM conversations c WHERE c.client_id = %s ORDER BY c.updated_at DESC LIMIT 100""",
        (cid,),
    )
    return {"conversations": rows}


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, x_client_id: str = Header(default="")) -> dict:
    conv = own_conversation(conversation_id, client_id(x_client_id))
    msgs = db.fetch_all(
        """SELECT m.id, m.role, m.content, m.search_query, m.sources, m.cited, m.usage, m.error, m.created_at,
                  f.rating AS feedback_rating, f.reasons AS feedback_reasons, f.comment AS feedback_comment
           FROM messages m LEFT JOIN feedback f ON f.message_id = m.id
           WHERE m.conversation_id = %s ORDER BY m.created_at""",
        (conversation_id,),
    )
    return {"conversation": conv, "messages": msgs}


class ConversationPatch(BaseModel):
    title: str = Field(min_length=1, max_length=120)


@router.patch("/conversations/{conversation_id}")
def rename_conversation(conversation_id: str, body: ConversationPatch, x_client_id: str = Header(default="")) -> dict:
    own_conversation(conversation_id, client_id(x_client_id))
    db.execute("UPDATE conversations SET title = %s WHERE id = %s", (body.title.strip(), conversation_id))
    return {"ok": True}


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, x_client_id: str = Header(default="")) -> dict:
    own_conversation(conversation_id, client_id(x_client_id))
    db.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
    return {"ok": True}


# ------------------------------------------------------------------ visszajelzés

class FeedbackRequest(BaseModel):
    message_id: str
    rating: str = Field(pattern="^(up|down)$")
    reasons: list[str] = []
    comment: str | None = Field(default=None, max_length=2000)


def _phoenix_annotation(trace_ref: str | None, rating: str, reasons: list[str], comment: str | None) -> None:
    """A visszajelzés a Phoenixben is megjelenik, a válasz trace-éhez kötve (span-annotáció)."""
    s = get_settings()
    if not s.phoenix_endpoint or not trace_ref or ":" not in trace_ref:
        return
    span_id = trace_ref.split(":", 1)[1]
    base = s.phoenix_endpoint.rsplit("/v1/", 1)[0]
    explanation = "; ".join(x for x in [", ".join(reasons), comment or ""] if x) or None
    body = {"data": [{"span_id": span_id, "name": "user_feedback", "annotator_kind": "HUMAN",
                      "result": {"label": "thumbs_up" if rating == "up" else "thumbs_down",
                                 "score": 1.0 if rating == "up" else 0.0, "explanation": explanation}}]}
    try:
        httpx.post(f"{base}/v1/span_annotations", json=body, timeout=10)
    except Exception as e:
        log.warning("Phoenix-annotáció hiba: %s", e)


@router.post("/feedback")
def feedback(body: FeedbackRequest, x_client_id: str = Header(default="")) -> dict:
    cid = client_id(x_client_id)
    msg = db.fetch_one(
        """SELECT m.id, m.trace_id FROM messages m JOIN conversations c ON c.id = m.conversation_id
           WHERE m.id = %s AND c.client_id = %s AND m.role = 'assistant'""",
        (body.message_id, cid),
    )
    if not msg:
        raise HTTPException(404, "nincs ilyen válasz")
    reasons = [r for r in body.reasons if r in REASON_CODES] if body.rating == "down" else []
    comment = (body.comment or "").strip() or None
    if body.rating == "down" and not reasons and not comment:
        raise HTTPException(400, "Negatív értékelésnél jelölj meg egy okot vagy írd le, mit vártál volna.")
    db.execute(
        """INSERT INTO feedback (message_id, rating, reasons, comment) VALUES (%s, %s, %s, %s)
           ON CONFLICT (message_id) DO UPDATE SET rating = EXCLUDED.rating, reasons = EXCLUDED.reasons,
               comment = EXCLUDED.comment, updated_at = now(), status = 'uj', status_at = NULL""",
        (body.message_id, body.rating, reasons, comment),
    )
    threading.Thread(target=_phoenix_annotation, args=(msg["trace_id"], body.rating, reasons, comment),
                     daemon=True).start()
    return {"ok": True}
