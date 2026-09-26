# Phase 2 — embed chunks into a personal PG Vector store

> Active change (proposed, not yet built). It extends the archived phase-1 change `2026-09-26-distiller-conversion-pipeline`, which produces the `chunks.jsonl` this phase consumes.

## Why

Phase 1 converts documents to Markdown and exports retrieval-ready chunks, but stops at files on disk. In the stakeholder's words: *"use my own pgvector and create agents with langraph later."*

The chunks only become useful when they are embedded and stored where they can be searched by meaning. This phase turns the exported `chunks.jsonl` into rows in Carlos's own Postgres + `pgvector` database and adds a similarity-search interface. That search interface is deliberately the seam a LangGraph agent will call later — agents themselves are a separate, future phase, but retrieval is designed now so they have a tool to consume.

Two decisions were taken with the stakeholder before writing this:

- **Embeddings use Voyage `voyage-3` (1024-dim).** Voyage is Anthropic's recommended embeddings partner and fits the Claude ecosystem. (Neither Groq nor Anthropic offers an embeddings API — settled in phase 1.)
- **The schema is independent of courier's.** distiller keeps its own `documents`/`chunks` tables tuned to its `chunks.jsonl`, not courier's Med/Grow `kb_documents`/`kb_chunks` model.

## What Changes

- **New capability `embedding`** (`src/distiller/embedding.py`): a provider-agnostic embedder with a Voyage `voyage-3` implementation. Uses Voyage's `input_type` (`document` when ingesting, `query` when searching), batches requests, retries transient failures with backoff, and pins the model + dimension in config. A chunk that cannot be embedded after retries fails its document rather than being silently dropped.
- **New capability `vector-store`** (`src/distiller/store.py`, Alembic migrations): an independent Postgres + `pgvector` schema — `documents` (identity `source_uri`, change anchor `content_sha256`) and `chunks` (FK to document, `embedding vector(1024)`, `UNIQUE(document_id, chunk_index)`), with an HNSW cosine index. Idempotent upsert keyed by `source_uri`: unchanged documents (matching `content_sha256`) are skipped; changed documents have their chunks replaced in place.
- **New capability `retrieval`** (`src/distiller/retrieval.py`): `search(query, top_k, filters)` embeds the query with `input_type=query` and returns the nearest chunks with their content, `source_uri`, `section`, `details` and similarity score — the interface future LangGraph agents call.
- **Ingest paths**: load an existing `chunks.jsonl` into the store (keeps conversion and vectorization separable), plus a one-shot "convert → embed → store" for a file. Exposed on the `distiller` CLI (`distiller store <file|jsonl>`, `distiller search "<query>"`) and as a Streamlit "Send to PG Vector" action.
- **Config additions**: `DATABASE_URL` (Carlos's own pgvector), `VOYAGE_API_KEY`, `EMBEDDING_MODEL=voyage-3`, `EMBEDDING_DIMENSIONS=1024`, `EMBED_BATCH_SIZE`. A `docker-compose.yml` with `pgvector/pgvector` is provided for local dev only.

## In scope

| Area | What is in |
|---|---|
| Embedding | Voyage `voyage-3` embedder behind a provider interface; input-type awareness; batching; retry/backoff; fail-loud on unembeddable chunks |
| Schema | Independent `documents` + `chunks` tables; `vector(1024)`; HNSW cosine index; Alembic migration; `CREATE EXTENSION vector` |
| Ingest | Idempotent upsert keyed by `source_uri`/`content_sha256`; load from `chunks.jsonl`; one-shot convert→embed→store |
| Retrieval | `search(query, top_k, filters)` returning chunks + metadata + score, query embedded with `input_type=query` |
| Interfaces | CLI `store` / `search` subcommands; Streamlit "Send to PG Vector"; async SQLAlchemy session helper |
| Config / dev | `DATABASE_URL`, `VOYAGE_API_KEY`, embedding settings; dev-only `docker-compose` with pgvector |

## Out of scope

- **LangGraph agents.** No graph, nodes, tools, or chat loop. This phase only delivers the retrieval interface an agent would call; the agent layer is phase 3.
- **Re-ranking, hybrid (BM25 + vector) search, query expansion.** Plain cosine top-k first; refinements later.
- **A retrieval HTTP/API server.** Search is a library function + CLI now; exposing it as a service is future.
- **Multi-tenant / access control** on the store. Single-owner, single database.
- **Changing phase-1 behaviour.** Conversion, chunking and the `chunks.jsonl` schema are fixed; this phase consumes them unchanged (it only adds the `embedding` column downstream).

## Non-goals

- Using Groq or Anthropic for embeddings (no embeddings API). Voyage is the choice; a local/OpenAI embedder may be added behind the same interface later, but not now.
- Making the schema courier-compatible. Independent by decision.
- Embedding index/TOC chunks — those are already filtered in phase 1 and never reach the store.
- Silent data loss: a chunk that fails to embed fails its document; a run that dropped content exits non-zero.

## Capabilities

### New Capabilities

- `embedding`: turning chunk text into vectors — the Voyage `voyage-3` provider, input-type handling, batching, retry, dimension pinning, and the fail-loud contract.
- `vector-store`: the independent Postgres + `pgvector` schema and the idempotent upsert that loads chunks into it keyed by document identity and content hash.
- `retrieval`: cosine similarity search returning chunks with metadata and score — the seam a LangGraph agent will consume.

### Modified Capabilities

None. `export`'s behaviour and `chunks.jsonl` schema are unchanged; that schema simply also serves as `vector-store`'s **input contract** (stated in the `vector-store` spec). This is a documented coupling, not a requirement change, so no `export` delta is included.

## Impact

- **distiller**: new `src/distiller/{embedding,store,retrieval}.py`, `alembic/` migrations, `docker-compose.yml`, CLI subcommands, a Streamlit action, and new deps (`sqlalchemy[asyncio]`, `asyncpg`, `pgvector`, `alembic`, `voyageai`).
- **External dependency**: requires a reachable Postgres with the `vector` extension (Carlos's own instance in production; the dev compose otherwise) and a Voyage API key.
- **Roadmap**: unblocks phase 3 (LangGraph agents) by providing `retrieval.search` as their tool. The `chunks.jsonl` from phase 1 is the durable hand-off between the two phases.
