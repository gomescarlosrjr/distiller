# Design — Phase 2 PG Vector embedding store

## Context

See proposal.md — Why. The constraints that shape the approach:

- **Phase 1 is the input.** The `chunks.jsonl` schema (`source_uri`, `content_sha256`, `chunk_index`, `content`, `section`, `details`, `char_len`, `token_estimate`) is fixed and already carries a document identity (`source_uri`) and a change anchor (`content_sha256`). Phase 2 adds only the `embedding` column downstream.
- **Carlos's own Postgres.** Production points at his instance via `DATABASE_URL`; a dev `docker-compose` with `pgvector/pgvector` exists only for local work.
- **courier is prior art, again.** Its ingest script solved idempotency (identity + checksum), fail-loud embedding (#158), and index filtering (already applied upstream in phase 1). Those patterns are reused; its Med/Grow schema is not.
- **Agents come later.** The retrieval interface must be a clean, stable function so a LangGraph tool can wrap it without reaching into the store internals.

Decisions below were taken with the stakeholder (embedding provider, schema independence) and from the phase-1 lineage.

## Goals / Non-Goals

**Goals:**
- Get phase-1 chunks into a searchable pgvector store idempotently.
- Retrieval that returns the right chunk with enough metadata to cite it.
- A retrieval seam ready for LangGraph without building the agent now.

**Non-Goals:**
- Anything under proposal.md — Out of scope and Non-goals: no agents, no hybrid/re-rank search, no API server, no multi-tenancy.

## Decisions

Each row: the decision, the alternatives rejected, and why.

### Embeddings

| Decision | Rejected | Why |
|---|---|---|
| **Voyage `voyage-3`, 1024-dim.** | OpenAI `text-embedding-3` (1536/3072); a pluggable-only spec with no default; a local model (Ollama) | Stakeholder chose Voyage — Anthropic's recommended partner, strong retrieval quality, fits the Claude ecosystem. A concrete default lets the schema pin `vector(1024)` now. |
| **Provider behind an `Embedder` protocol.** | call the Voyage SDK directly throughout | One seam keeps a future OpenAI/local embedder a drop-in, and makes tests use a fake embedder with no network. |
| **Use Voyage `input_type`: `document` on ingest, `query` on search.** | one embedding call shape for both | Voyage (and asymmetric models generally) improve when documents and queries are embedded with their roles declared; ignoring it leaves recall on the table. |
| **A chunk that fails to embed after retries fails its document; the run exits non-zero.** | skip the chunk and continue | courier's #158 lesson: a silently shrunk knowledge base is an invisible RAG regression. Fail loud. |

### Schema & store

| Decision | Rejected | Why |
|---|---|---|
| **Independent `documents` + `chunks` schema.** | mirror courier's `kb_documents`/`kb_chunks` | Stakeholder chose independence. courier's model carries product/domain/ingest_status fields distiller does not need; a lean schema matched to `chunks.jsonl` is simpler and owns its own evolution. |
| **Identity = `source_uri`; change anchor = `content_sha256`.** | a surrogate id only; hash-only identity | Mirrors phase 1 and courier: re-ingesting the same file updates one document; an unchanged checksum skips work; a changed checksum replaces that document's chunks. `UNIQUE(document_id, chunk_index)` turns accidental duplication into a DB error, not a silent quality loss. |
| **HNSW index with `vector_cosine_ops`.** | IVFFlat; no index (seq scan) | HNSW gives better recall/latency without a training step and suits an incrementally growing personal store; cosine matches Voyage's normalized embeddings. IVFFlat needs a populated table to train `lists` well. |
| **SQLAlchemy async + asyncpg + `pgvector` + Alembic.** | raw psycopg + hand SQL; sync SQLAlchemy | Matches courier's tooling (familiar, migration-tracked) and the async pipeline; `pgvector`'s SQLAlchemy type keeps the vector column first-class. |
| **Migrations, not `create_all`.** | `Base.metadata.create_all` | The `vector` extension and the HNSW index need explicit DDL; a migration is the honest place for `CREATE EXTENSION` and index tuning, and it versions schema changes. |

### Ingest & retrieval

| Decision | Rejected | Why |
|---|---|---|
| **Primary ingest reads `chunks.jsonl`; a one-shot convert→embed→store also exists.** | only a one-shot in-memory path | Reading the JSONL keeps conversion (heavy, Docling/torch) and vectorization (network, DB) separable and re-runnable, and makes the phase-1 export the durable hand-off. The one-shot is a convenience over the same store functions. |
| **`search(query, top_k, filters)` returns chunk content + `source_uri` + `section` + `details` + score.** | return bare text; return ORM rows | An agent needs to cite the source and section and to see the score; returning plain dicts (not ORM objects) keeps the interface stable and detached from the session. |
| **Retrieval is a library function + CLI now, not a service.** | stand up a FastAPI retrieval server | The only near-term consumer is a local LangGraph agent (phase 3), which imports the function. A service is ceremony until something remote needs it. |
| **Metadata filters applied in SQL before ranking.** | fetch top-k then filter in Python | Filtering candidates first (e.g. by `source_uri`) keeps recall correct — post-filtering a fixed top-k can return fewer than `k` or miss matches. |

### Enabling LangGraph (phase 3, not built here)

| Decision | Rejected | Why |
|---|---|---|
| **Freeze `retrieval.search` as the tool boundary; design nothing else agent-shaped yet.** | scaffold a LangGraph graph now | The stakeholder wants agents "later." Committing to a graph, memory model or LLM now would guess requirements. A stable retrieval function is the one thing the agent will certainly need, so it is the only thing this phase promises it. |
