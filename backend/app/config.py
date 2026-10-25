"""Beállítások a .env-ből (a docker-compose `env_file`-ja adja át)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


def _csv(value: str) -> list[str]:
    return [x.strip() for x in value.split(",") if x.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ---- Postgres
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "utmutato"
    postgres_user: str = "utmutato"
    postgres_password: str = ""

    # ---- tárhely
    store_path: str = "/data/store"
    seed_path: str = "/data/seed"
    eval_path: str = "/eval"

    # ---- OpenRouter
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    chat_model: str = "openai/gpt-4o-mini"
    rewrite_model: str = "openai/gpt-4o-mini"
    embed_model: str = "baai/bge-m3"
    eval_embed_models: str = "baai/bge-m3,openai/text-embedding-3-small,qwen/qwen3-embedding-8b"
    rerank_model: str = "cohere/rerank-v3.5"
    vlm_model: str = "openai/gpt-4o-mini"
    judge_model: str = "openai/gpt-4o-mini"
    llm_temperature: float = 0.1
    llm_timeout_s: int = 120

    # ---- admin
    admin_secret: str = ""

    # ---- beolvasás
    ocr_langs: str = "hu,en"
    scanned_min_chars_per_page: int = 50
    images_scale: float = 2.0
    document_timeout_s: int = 1800
    docling_threads: int = 0

    # ---- képek
    image_min_px: int = 120
    image_repeat_docs: int = 3
    image_max_per_doc: int = 80

    # ---- chunkolás
    chunk_strategies: str = "hybrid,fixed"
    chat_strategy: str = "hybrid"
    chunk_tokenizer: str = "BAAI/bge-m3"
    chunk_max_tokens: int = 400
    chunk_overlap_tokens: int = 60

    # ---- keresés
    dense_candidates: int = 40
    bm25_candidates: int = 40
    rrf_k: int = 60
    rerank_candidates: int = 25
    top_k: int = 6
    rerank_min_score: float = 0.15
    max_images: int = 6

    # ---- chat
    history_messages: int = 6
    max_source_chars: int = 2500

    # ---- Phoenix
    phoenix_endpoint: str = ""
    phoenix_project: str = "utmutato-asszisztens"
    phoenix_ui_url: str = "http://localhost:6070"   # a böngészőből elérhető Phoenix (admin-link)

    # ---- worker
    worker_poll_s: float = 2.0

    @property
    def ocr_lang_list(self) -> list[str]:
        return _csv(self.ocr_langs)

    @property
    def strategy_list(self) -> list[str]:
        return _csv(self.chunk_strategies)

    @property
    def eval_embed_model_list(self) -> list[str]:
        return _csv(self.eval_embed_models)

    @property
    def dsn(self) -> str:
        return (
            f"host={self.postgres_host} port={self.postgres_port} dbname={self.postgres_db} "
            f"user={self.postgres_user} password={self.postgres_password}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
