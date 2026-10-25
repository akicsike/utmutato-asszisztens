"""A mérőszkriptek közös része: backend-import, Phoenix (külön "-eval" projekt), LLM-bíró, eredménymentés."""

from __future__ import annotations

import json
import logging
import statistics
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, "/app")

from psycopg.types.json import Jsonb  # noqa: E402

from app import db, llm  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.telemetry import init_tracing  # noqa: E402

HERE = Path(__file__).parent
RESULTS = HERE / "results"
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


def setup() -> None:
    s = get_settings()
    init_tracing(f"{s.phoenix_project}-eval")


def flush_traces() -> None:
    try:
        from opentelemetry import trace

        trace.get_tracer_provider().force_flush()  # type: ignore[attr-defined]
    except Exception:
        pass


def load_yaml(name: str) -> list[dict]:
    return yaml.safe_load((HERE / "datasets" / name).read_text(encoding="utf-8"))


def feedback_cases(level: str) -> list[dict]:
    """Az adminon visszajelzésből felvett mérési esetek (eval_cases tábla) a YAML-kérdéssor formátumában, „fb<id>”
    azonosítóval – a mérés a kérdéssor mellett ezeket is futtatja (regressziós teszt a javított hibákra)."""
    rows = db.fetch_all("SELECT * FROM eval_cases WHERE level = %s ORDER BY id", (level,))
    if level == "rag":
        return [{"id": f"fb{r['id']}", "question": r["question"], "doc": r["doc_file"], "pages": r["pages"],
                 "keywords": []} for r in rows]
    return [{"id": f"fb{r['id']}", "question": r["question"], "expect": r["expect"], "facts": r["facts"] or []}
            for r in rows]


def mean(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(statistics.fmean(xs), 4) if xs else None


def pct(xs, q: float) -> float | None:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 1)


def judge(system: str, payload: dict, max_tokens: int = 700) -> dict:
    """LLM-as-judge: JSON-válasz; hibánál üres dict (a mérés ne álljon le egy rossz válasz miatt)."""
    s = get_settings()
    for attempt in range(3):
        try:
            raw = llm.chat([{"role": "system", "content": system},
                            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                           model=s.judge_model, purpose="judge", json_mode=True, max_tokens=max_tokens, temperature=0)
            return json.loads(raw)
        except Exception as e:
            logging.warning("bíró hiba (%s): %s", attempt + 1, e)
            time.sleep(2)
    return {}


def save_run(level: str, name: str, config: dict, summary: dict, results: list[dict]) -> int:
    RESULTS.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = RESULTS / f"{level}_{stamp}.json"
    out.write_text(json.dumps({"level": level, "name": name, "config": config, "summary": summary,
                               "results": results}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    row = db.fetch_one(
        "INSERT INTO eval_runs (level, name, config, summary, results) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (level, name, Jsonb(config), Jsonb(summary), Jsonb(json.loads(json.dumps(results, default=str)))))
    print(f"\nmentve: eval_runs #{row['id']}  +  {out}")
    return row["id"]


def phoenix_annotate(trace_ref: str | None, annotations: list[dict]) -> None:
    """Az LLM-bíró eredménye a Phoenixben is: span-annotáció a válasz trace-ének gyökér-spanjára."""
    import httpx

    s = get_settings()
    if not s.phoenix_endpoint or not trace_ref or ":" not in trace_ref:
        return
    span_id = trace_ref.split(":", 1)[1]
    base = s.phoenix_endpoint.rsplit("/v1/", 1)[0]
    data = [{"span_id": span_id, "name": a["name"], "annotator_kind": "LLM",
             "result": {k: a[k] for k in ("label", "score", "explanation") if a.get(k) is not None}} for a in annotations]
    try:
        flush_traces()
        httpx.post(f"{base}/v1/span_annotations", json={"data": data}, timeout=15)
    except Exception as e:
        logging.warning("Phoenix-annotáció hiba: %s", e)
