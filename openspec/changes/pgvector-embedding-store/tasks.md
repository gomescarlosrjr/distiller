# Tasks — Phase 2 PG Vector embedding store

Proposed work; nothing is implemented yet. Each task names the file it lands in and how it will be verified (tests to be added under `tests/`). Implementation happens on a feature branch off `distiller`, then a PR.

## 1. Dependencies & config

- [ ] 1.1 Add deps to `pyproject.toml`: `sqlalchemy[asyncio]`, `asyncpg`, `pgvector`, `alembic`, `voyageai`. Verify: `uv sync` resolves.
- [ ] 1.2 Extend `src/distiller/config.py` with `database_url` (`DATABASE_URL`), `voyage_api_key` (`VOYAGE_API_KEY`), `embedding_model` (default `voyage-3`), `embedding_dimensions` (default `1024`), `embed_batch_size`. Update `.env.example`. Verify: settings load; a test asserts defaults.
- [ ] 1.3 Add a dev-only `docker-compose.yml` using `pgvector/pgvector:pg16` and document it in the README as local-dev only. Verify: `docker compose up` yields a DB where `CREATE EXTENSION vector` succeeds.

## 2. Embedding (capability: embedding)

- [ ] 2.1 Define an `Embedder` protocol (`embed_documents(texts)`, `embed_query(text)`) in `src/distiller/embedding.py`. Verify: unit test with a fake embedder.
- [ ] 2.2 Implement `VoyageEmbedder` calling `voyage-3` with `input_type="document"` / `"query"`, batching up to `embed_batch_size`, returning 1024-dim vectors. Verify: test with the Voyage client mocked asserts input_type and batch shape.
- [ ] 2.3 Retry transient failures with exponential backoff; after the cap, raise so the caller fails the document (never silently drop a chunk). Verify: test that exhausted retries raise, not return partial.
- [ ] 2.4 Guard that returned vector length equals `embedding_dimensions`. Verify: test rejects a mismatched dimension.

## 3. Schema & store (capability: vector-store)

- [ ] 3.1 SQLAlchemy async models in `src/distiller/store.py`: `Document` (`id`, `source_uri` UNIQUE, `content_sha256`, `media_type`, `title`, `created_at`, `updated_at`) and `Chunk` (`id`, `document_id` FK cascade, `chunk_index`, `content`, `section`, `details` JSONB, `char_len`, `token_estimate`, `embedding vector(1024)`, `UNIQUE(document_id, chunk_index)`). Verify: models import; metadata creates on a test DB.
- [ ] 3.2 Alembic migration: `CREATE EXTENSION IF NOT EXISTS vector`, both tables, and an HNSW index on `chunk.embedding` with `vector_cosine_ops`. Verify: `alembic upgrade head` on a fresh pgvector DB; index present.
- [ ] 3.3 Async session helper (`get_session`) reading `database_url`. Verify: connects to the dev compose DB.
- [ ] 3.4 Idempotent `upsert_document(record_group)`: identity `source_uri`; skip when `content_sha256` unchanged; on change, delete existing chunks and re-insert. Verify: test that re-ingesting identical bytes inserts once; changed bytes replace chunks; `UNIQUE(document_id, chunk_index)` holds.
- [ ] 3.5 A run that dropped any chunk marks the document failed and the process exits non-zero. Verify: test with a failing embedder asserts non-zero outcome and no partial "ready" document.

## 4. Ingest paths

- [ ] 4.1 `load_jsonl(path)` → group records by document → embed → upsert. Verify: end-to-end test from a fixture `chunks.jsonl` into a test DB; row counts match.
- [ ] 4.2 One-shot `ingest_file(path)` = phase-1 `process_document` → embed → upsert, reusing `pipeline.process_document`. Verify: test converts a small fixture and stores it.

## 5. Retrieval (capability: retrieval)

- [ ] 5.1 `search(query, top_k=5, filters=None)` in `src/distiller/retrieval.py`: embed the query with `input_type="query"`, order by cosine distance, return `[{content, source_uri, section, details, score}]`. Verify: test inserts known chunks and asserts the semantically closest ranks first.
- [ ] 5.2 Optional metadata filters (e.g. `source_uri`, `details.chunk_profile`) applied in SQL before ranking. Verify: test that a filter restricts the candidate set.
- [ ] 5.3 Document `search` as the stable interface a future LangGraph tool will wrap. Verify: docstring + README note; signature covered by a test.

## 6. Interfaces

- [ ] 6.1 CLI: `distiller store <file|chunks.jsonl>` and `distiller search "<query>" [--top-k]`. Verify: CLI tests via the entry point against the dev DB.
- [ ] 6.2 Streamlit: a "Send to PG Vector" action on a converted document and a small search box over the store. Verify: manual run against the dev DB; app imports cleanly.

## 7. Verification of the whole

- [ ] 7.1 `uv run pytest` green, including new embedding/store/retrieval tests (Voyage + DB mocked or against the dev compose). 
- [ ] 7.2 Manual acceptance: convert a real PDF (phase 1), `distiller store` it, `distiller search` a known phrase, confirm the right chunk returns with its `source_uri`/`section`.
- [ ] 7.3 Re-run `distiller store` on the same file; confirm no duplicate rows (idempotency).
