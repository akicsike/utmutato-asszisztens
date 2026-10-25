"""OpenRouter-kliens: chat (sima és streamelt), embedding, rerank, képleírás (VLM).

Minden hívás a `llm_usage` táblába kerül: modell, tokenek, költség (USD), idő (és streamnél az első token ideje).
A költséget az OpenRouter maga adja vissza (`usage.cost`, ha a kérésben `usage.include = true`); ha valamelyik
végpont nem adja, a modell árlistájából számoljuk (/models, /embeddings/models – egyszer lekérve, gyorsítótárban).
A chat- és embedding-hívásokat az OpenInference-instrumentáció automatikusan Phoenixbe is küldi (telemetry.py).
"""

from __future__ import annotations

import base64
import logging
import threading
import time
from typing import Any, Iterator

import httpx
from openai import OpenAI

from . import db
from .config import get_settings

log = logging.getLogger(__name__)

_client: OpenAI | None = None
_pricing: dict[str, tuple[float, float]] | None = None
_pricing_lock = threading.Lock()
USAGE_INCLUDE = {"usage": {"include": True}}


def client() -> OpenAI:
    global _client
    if _client is None:
        s = get_settings()
        if not s.openrouter_api_key:
            raise RuntimeError("Hiányzik az OPENROUTER_API_KEY (.env)")
        _client = OpenAI(
            api_key=s.openrouter_api_key, base_url=s.openrouter_base_url, timeout=s.llm_timeout_s,
            default_headers={"HTTP-Referer": "http://localhost:8070", "X-Title": "Utmutato asszisztens"},
        )
    return _client


# ------------------------------------------------------------------ költség

def pricing() -> dict[str, tuple[float, float]]:
    """modell -> (prompt $/token, completion $/token) az OpenRouter árlistájából (egyszer lekérve)."""
    global _pricing
    with _pricing_lock:
        if _pricing is not None:
            return _pricing
        s = get_settings()
        out: dict[str, tuple[float, float]] = {}
        headers = {"Authorization": f"Bearer {s.openrouter_api_key}"}
        for path in ("/models", "/embeddings/models"):
            try:
                r = httpx.get(s.openrouter_base_url + path, headers=headers, timeout=30)
                for m in r.json().get("data", []):
                    p = m.get("pricing") or {}
                    out[m["id"]] = (float(p.get("prompt") or 0), float(p.get("completion") or 0))
            except Exception as e:  # az árlista hiánya ne állítsa meg a hívást
                log.warning("árlista nem érhető el (%s): %s", path, e)
        _pricing = out
        return out


def _usage_value(usage: Any, key: str):
    if usage is None:
        return None
    if isinstance(usage, dict):
        return usage.get(key)
    val = getattr(usage, key, None)
    if val is None:
        extra = getattr(usage, "model_extra", None) or {}
        val = extra.get(key)
    return val


def compute_cost(model: str, usage: Any) -> float | None:
    cost = _usage_value(usage, "cost")
    if cost is not None:
        return float(cost)
    pt = _usage_value(usage, "prompt_tokens") or 0
    ct = _usage_value(usage, "completion_tokens") or 0
    price = pricing().get(model)
    if not price:
        return None
    return pt * price[0] + ct * price[1]


def log_usage(purpose: str, model: str, usage: Any = None, latency_ms: int | None = None, ttft_ms: int | None = None,
              message_id: str | None = None, document_id: int | None = None, ok: bool = True,
              error: str | None = None, cost: float | None = None) -> dict:
    pt = _usage_value(usage, "prompt_tokens")
    ct = _usage_value(usage, "completion_tokens")
    tt = _usage_value(usage, "total_tokens") or ((pt or 0) + (ct or 0) or None)
    if cost is None and usage is not None:
        cost = compute_cost(model, usage)
    rec = {"purpose": purpose, "model": model, "prompt_tokens": pt, "completion_tokens": ct, "total_tokens": tt,
           "cost_usd": cost, "latency_ms": latency_ms, "ttft_ms": ttft_ms}
    try:
        db.execute(
            """INSERT INTO llm_usage (purpose, model, prompt_tokens, completion_tokens, total_tokens, cost_usd,
                                      latency_ms, ttft_ms, message_id, document_id, ok, error)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (purpose, model, pt, ct, tt, cost, latency_ms, ttft_ms, message_id, document_id, ok, (error or "")[:500] or None),
        )
    except Exception as e:  # a naplózás hibája ne állítsa meg a választ
        log.warning("llm_usage naplózás hiba: %s", e)
    return rec


# ------------------------------------------------------------------ chat

def chat(messages: list[dict], model: str | None = None, purpose: str = "chat", temperature: float | None = None,
         max_tokens: int | None = None, json_mode: bool = False, message_id: str | None = None,
         document_id: int | None = None) -> str:
    s = get_settings()
    model = model or s.chat_model
    kwargs: dict[str, Any] = {"model": model, "messages": messages,
                              "temperature": s.llm_temperature if temperature is None else temperature,
                              "extra_body": USAGE_INCLUDE}
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    t0 = time.time()
    try:
        resp = client().chat.completions.create(**kwargs)
    except Exception as e:
        log_usage(purpose, model, None, int((time.time() - t0) * 1000), message_id=message_id,
                  document_id=document_id, ok=False, error=str(e))
        raise
    log_usage(purpose, model, resp.usage, int((time.time() - t0) * 1000), message_id=message_id, document_id=document_id)
    return (resp.choices[0].message.content or "").strip()


def chat_stream(messages: list[dict], model: str | None = None, purpose: str = "chat",
                temperature: float | None = None, message_id: str | None = None) -> Iterator[dict]:
    """Streamelt válasz. Elemek: {"type": "delta", "text": ...} …, a végén {"type": "usage", ...}."""
    s = get_settings()
    model = model or s.chat_model
    t0 = time.time()
    ttft = None
    usage = None
    try:
        stream = client().chat.completions.create(
            model=model, messages=messages, stream=True,
            temperature=s.llm_temperature if temperature is None else temperature,
            stream_options={"include_usage": True}, extra_body=USAGE_INCLUDE,
        )
        for chunk in stream:
            if chunk.usage is not None:
                usage = chunk.usage
            if chunk.choices:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    if ttft is None:
                        ttft = int((time.time() - t0) * 1000)
                    yield {"type": "delta", "text": delta}
    except Exception as e:
        log_usage(purpose, model, usage, int((time.time() - t0) * 1000), ttft, message_id=message_id,
                  ok=False, error=str(e))
        raise
    rec = log_usage(purpose, model, usage, int((time.time() - t0) * 1000), ttft, message_id=message_id)
    yield {"type": "usage", **rec}


# ------------------------------------------------------------------ embedding

def embed(texts: list[str], model: str | None = None, purpose: str = "embed", document_id: int | None = None,
          batch_size: int = 64, message_id: str | None = None) -> list[list[float]]:
    s = get_settings()
    model = model or s.embed_model
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = [t if t.strip() else " " for t in texts[i:i + batch_size]]
        t0 = time.time()
        for attempt in range(4):
            try:
                resp = client().embeddings.create(model=model, input=batch, extra_body=USAGE_INCLUDE)
                break
            except Exception as e:
                if attempt == 3:
                    log_usage(purpose, model, None, int((time.time() - t0) * 1000), document_id=document_id,
                              message_id=message_id, ok=False, error=str(e))
                    raise
                time.sleep(2 * (attempt + 1))
        data = sorted(resp.data, key=lambda d: d.index)
        out.extend(d.embedding for d in data)
        log_usage(purpose, model, resp.usage, int((time.time() - t0) * 1000), document_id=document_id,
                  message_id=message_id)
    return out


# ------------------------------------------------------------------ rerank

def rerank(query: str, documents: list[str], model: str | None = None, message_id: str | None = None) -> list[float]:
    """Pontszám (0..1) minden dokumentumra, az eredeti sorrendben (OpenRouter /rerank)."""
    if not documents:
        return []
    s = get_settings()
    model = model or s.rerank_model
    t0 = time.time()
    try:
        r = httpx.post(
            s.openrouter_base_url + "/rerank",
            headers={"Authorization": f"Bearer {s.openrouter_api_key}"},
            json={"model": model, "query": query, "documents": documents, "top_n": len(documents)},
            timeout=s.llm_timeout_s,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log_usage("rerank", model, None, int((time.time() - t0) * 1000), message_id=message_id, ok=False, error=str(e))
        raise
    scores = [0.0] * len(documents)
    for item in data.get("results", []):
        scores[item["index"]] = float(item.get("relevance_score", 0.0))
    usage = data.get("usage") or {}
    log_usage("rerank", model, usage or None, int((time.time() - t0) * 1000), message_id=message_id,
              cost=usage.get("cost") if isinstance(usage, dict) else None)
    return scores


# ------------------------------------------------------------------ képleírás (VLM)

def vision(prompt: str, image: bytes, mime: str = "image/png", system: str | None = None, model: str | None = None,
           purpose: str = "vlm", document_id: int | None = None, max_tokens: int = 350, detail: str = "low") -> str:
    """Képleírás. A "low" detail fix, kis tokenszám (a gpt-4o-mininél a nagy felbontású kép drága)."""
    s = get_settings()
    model = model or s.vlm_model
    url = f"data:{mime};base64,{base64.b64encode(image).decode()}"
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": url, "detail": detail}},
    ]})
    return chat(messages, model=model, purpose=purpose, max_tokens=max_tokens, document_id=document_id)
