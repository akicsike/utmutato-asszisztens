"""FastAPI alkalmazás: chat (SSE), beszélgetések, visszajelzés, fájlok, admin – és a React UI kiszolgálása."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db, jobs
from .api import admin_docs, admin_insights, chat, files
from .config import get_settings
from .migrate import migrate
from .telemetry import init_tracing

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
STATIC = Path(__file__).parent.parent / "static"   # a lefordított React UI (a Dockerfile másolja ide)


@asynccontextmanager
async def lifespan(_: FastAPI):
    migrate()
    db.reset_pool()
    init_tracing()
    yield


TRACED_PATHS = ("/api/chat", "/api/feedback")


def _untraced(scope) -> bool:
    """A FastAPI (0.16x) beépített OpenTelemetry-támogatása a Phoenix globális tracer providerén minden HTTP-kérésből
    trace-t csinálna (képek, statikus fájlok, /health, admin-lekérdezések): ezek elnyomnák a chatet a Phoenixben, és a
    P50 latencia ~4 ms lett. Csak a chat és a visszajelzés kérése marad; a többi kérésen belüli LLM-hívás (pl. a
    visszajelzés-elemzés) az OpenAI-instrumentációtól így is kap saját trace-t."""
    return scope.get("type") != "http" or scope.get("path") not in TRACED_PATHS


app = FastAPI(title="Használati útmutató asszisztens", lifespan=lifespan,
              telemetry={"exclude": _untraced, "operation_spans": False, "metrics": False})
app.include_router(admin_docs.router)
app.include_router(admin_insights.router)
app.include_router(chat.router)
app.include_router(files.router)


@app.get("/health")
def health() -> dict:
    s = get_settings()
    docs = db.fetch_one(
        "SELECT count(*) AS n, count(*) FILTER (WHERE status = 'indexed') AS indexed FROM documents")
    return {"ok": True, "documents": docs, "queue": jobs.queue_status(), "chat_model": s.chat_model,
            "embed_model": s.embed_model, "rerank_model": s.rerank_model, "strategy": s.chat_strategy,
            "phoenix": bool(s.phoenix_endpoint)}


# ---- React UI (SPA): a /api, /files, /images, /health útvonalakon kívül minden az index.html
if STATIC.is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        target = STATIC / path
        if path and target.is_file():
            return FileResponse(target)
        return FileResponse(STATIC / "index.html")
