"""Mindhárom mérési szint egymás után: embedding-előkészítés -> RAG -> prompt -> alkalmazás.
Futtatás: docker compose exec api python /eval/run_all.py
"""

import app_eval
import embed_models
import prompt_eval
import rag_eval

if __name__ == "__main__":
    print("== embedding-modellek előkészítése ==")
    embed_models.main()
    print("\n== 1. RAG-szint ==")
    rag_eval.main()
    print("\n== 2. prompt-szint ==")
    prompt_eval.main()
    print("\n== 3. alkalmazás-szint ==")
    app_eval.main()
