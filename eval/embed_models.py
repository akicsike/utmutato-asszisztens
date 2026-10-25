"""Az összehasonlítandó embedding-modellekkel (EVAL_EMBED_MODELS) is beágyazza a chunkokat.

A chat csak az EMBED_MODEL-t használja; a többi modell vektorai ugyanabba az `embeddings` táblába kerülnek
(kulcs: chunk_id + model), így a keresés modellenként futtatható. Csak a hiányzó vektorok készülnek el.
"""

from __future__ import annotations

import numpy as np

from common import db, get_settings, llm


def ensure(model: str, strategies: list[str]) -> None:
    for strategy in strategies:
        rows = db.fetch_all(
            """SELECT c.id, c.embed_text FROM chunks c
               WHERE c.strategy = %s AND NOT EXISTS
                     (SELECT 1 FROM embeddings e WHERE e.chunk_id = c.id AND e.model = %s)
               ORDER BY c.id""", (strategy, model))
        if not rows:
            print(f"  {model} / {strategy}: kész")
            continue
        print(f"  {model} / {strategy}: {len(rows)} chunk beágyazása…")
        vectors = llm.embed([r["embed_text"] for r in rows], model=model, purpose="embed_eval")
        with db.conn() as c, c.cursor() as cur:
            cur.executemany("INSERT INTO embeddings (chunk_id, model, embedding) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                            [(r["id"], model, np.asarray(v, dtype=np.float32)) for r, v in zip(rows, vectors)])
        print(f"    dim={len(vectors[0])}")


def main() -> None:
    s = get_settings()
    for model in s.eval_embed_model_list:
        try:
            ensure(model, s.strategy_list)
        except Exception as e:
            print(f"  {model}: HIBA – kihagyva ({e})")


if __name__ == "__main__":
    main()
