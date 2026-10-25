-- Használati útmutató asszisztens – kezdő séma
CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------- dokumentumok
CREATE TABLE documents (
    id            serial PRIMARY KEY,
    title         text NOT NULL,                 -- megjelenített cím (LLM a fájlnévből + első oldalból, admin átírhatja)
    product       text,                          -- termék típusa (kávégép, mosogatógép …)
    brand         text,
    filename      text NOT NULL,                 -- az eredeti fájlnév
    file_hash     text NOT NULL UNIQUE,          -- sha256 – ugyanaz a fájl kétszer nem kerül be
    file_size     bigint,
    source        text NOT NULL DEFAULT 'upload',-- upload | seed
    pages         int,
    status        text NOT NULL DEFAULT 'queued',-- queued | parsing | images | indexing | indexed | error
    stage_info    text,                          -- a worker aktuális lépése (pl. "képek 12/40")
    scanned       boolean,                       -- nincs érdemi szövegréteg -> teljes oldalas OCR
    ocr_pages     int[] NOT NULL DEFAULT '{}',   -- szövegréteg nélküli oldalak
    parse_mode    text,
    parse_seconds real,
    index_seconds real,
    n_chunks      int NOT NULL DEFAULT 0,
    n_images      int NOT NULL DEFAULT 0,
    manual_fields text[] NOT NULL DEFAULT '{}',  -- admin által átírt mezők (újrabeolvasáskor megmaradnak)
    error         text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- képek
CREATE TABLE images (
    id             serial PRIMARY KEY,
    document_id    int NOT NULL REFERENCES documents ON DELETE CASCADE,
    item_ref       text,                         -- Docling hivatkozás (#/pictures/12)
    page           int,
    bbox           jsonb,
    path           text NOT NULL,                -- a store-hoz relatív út
    width          int,
    height         int,
    phash          text,
    caption        text,                         -- "3. ábra: Víztartály" (Docling vagy a közeli felirat)
    section        text,                         -- a kép fejezetútja
    ocr_text       text,
    description    text,                         -- VLM-leírás
    vlm_model      text,
    skipped_reason text,                         -- szűrés oka (túl kicsi, ismétlődő logó …)
    manual_hidden  boolean,                      -- admin döntése (felülírja a szűrést)
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX images_document_idx ON images (document_id);
CREATE INDEX images_phash_idx ON images (phash);

-- ---------------------------------------------------------------- chunkok + embeddingek
CREATE TABLE chunks (
    id          serial PRIMARY KEY,
    document_id int NOT NULL REFERENCES documents ON DELETE CASCADE,
    strategy    text NOT NULL,                   -- hybrid | fixed | image
    seq         int NOT NULL,
    kind        text NOT NULL DEFAULT 'text',    -- text | image
    text        text NOT NULL,                   -- ezt mutatjuk forrásként és ezt kapja az LLM
    embed_text  text NOT NULL,                   -- kontextus-előtag + fejezetút + szöveg (embedding + BM25)
    section     text,
    page_from   int,
    page_to     int,
    image_ids   int[] NOT NULL DEFAULT '{}',     -- a chunkhoz kötött képek (azonos oldal / fejezet)
    token_count int,
    extra       jsonb
);
CREATE INDEX chunks_strategy_idx ON chunks (strategy);
CREATE INDEX chunks_document_idx ON chunks (document_id);

-- Egy chunknak modellenként egy embeddingje lehet: így az embedding-modellek összevethetők (RAG-szintű mérés).
-- A dimenzió modellenként más, ezért a vektor oszlop dimenzió nélküli; ~5000 chunknál a pontos (index nélküli)
-- koszinusz-keresés is ezredmásodpercek alatt fut.
CREATE TABLE embeddings (
    chunk_id  int NOT NULL REFERENCES chunks ON DELETE CASCADE,
    model     text NOT NULL,
    embedding vector NOT NULL,
    PRIMARY KEY (chunk_id, model)
);
CREATE INDEX embeddings_model_idx ON embeddings (model);

-- A BM25-index gyorsítótárának érvényessége stratégiánként (indexeléskor nő).
CREATE TABLE index_state (
    strategy   text PRIMARY KEY,
    version    bigint NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- feladatsor (worker)
CREATE TABLE jobs (
    id          bigserial PRIMARY KEY,
    document_id int REFERENCES documents ON DELETE CASCADE,
    kind        text NOT NULL,                   -- process | reindex | images
    status      text NOT NULL DEFAULT 'queued',  -- queued | running | done | error
    error       text,
    attempts    int NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now(),
    started_at  timestamptz,
    finished_at timestamptz
);
CREATE INDEX jobs_status_idx ON jobs (status, id);

-- ---------------------------------------------------------------- beszélgetések
CREATE TABLE conversations (
    id         uuid PRIMARY KEY,
    client_id  text NOT NULL,                    -- a böngésző azonosítója (localStorage)
    title      text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX conversations_client_idx ON conversations (client_id, updated_at DESC);

CREATE TABLE messages (
    id              uuid PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES conversations ON DELETE CASCADE,
    role            text NOT NULL,               -- user | assistant
    content         text NOT NULL DEFAULT '',
    search_query    text,                        -- az önálló keresőkérdés (átírás után)
    sources         jsonb,                       -- a válasz forrásai (a UI bal paneljéhez)
    images          jsonb,
    cited           int[],
    usage           jsonb,                       -- tokenek, költség, TTFT, teljes idő
    trace_id        text,                        -- Phoenix trace
    error           text,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX messages_conversation_idx ON messages (conversation_id, created_at);

-- ---------------------------------------------------------------- visszajelzés
CREATE TABLE feedback (
    id         serial PRIMARY KEY,
    message_id uuid NOT NULL UNIQUE REFERENCES messages ON DELETE CASCADE,
    rating     text NOT NULL CHECK (rating IN ('up', 'down')),
    reasons    text[] NOT NULL DEFAULT '{}',     -- téves | nem_talalta | hianyos | rossz_forras | rossz_kep | nehezen_ertheto
    comment    text,                             -- "Mit vártál volna?"
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE feedback_analyses (
    id         serial PRIMARY KEY,
    model      text,
    n_feedback int,
    result     jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- LLM-használat (token, költség, idő)
CREATE TABLE llm_usage (
    id                bigserial PRIMARY KEY,
    created_at        timestamptz NOT NULL DEFAULT now(),
    purpose           text NOT NULL,             -- chat | rewrite | embed | rerank | vlm | metadata | judge | eval
    model             text NOT NULL,
    prompt_tokens     int,
    completion_tokens int,
    total_tokens      int,
    cost_usd          double precision,
    latency_ms        int,
    ttft_ms           int,                       -- első token ideje (streamelt válasznál)
    message_id        uuid,
    document_id       int,
    ok                boolean NOT NULL DEFAULT true,
    error             text
);
CREATE INDEX llm_usage_created_idx ON llm_usage (created_at);
CREATE INDEX llm_usage_message_idx ON llm_usage (message_id);

-- ---------------------------------------------------------------- mérések
CREATE TABLE eval_runs (
    id         serial PRIMARY KEY,
    level      text NOT NULL,                    -- rag | prompt | app
    name       text NOT NULL,
    config     jsonb,
    summary    jsonb,
    results    jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
