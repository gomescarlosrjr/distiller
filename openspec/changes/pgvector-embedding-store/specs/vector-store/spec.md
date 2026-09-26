## Purpose

The independent Postgres + `pgvector` schema and the idempotent ingest that loads phase-1 chunks into it, keyed by document identity and content hash, with the `chunks.jsonl` record as the input contract.

## ADDED Requirements

### Requirement: Independent documents and chunks schema
The store SHALL define two tables. `documents`: `id`, `source_uri` (UNIQUE, the identity), `content_sha256`, `media_type`, `title`, `created_at`, `updated_at`. `chunks`: `id`, `document_id` (FK to `documents`, ON DELETE CASCADE), `chunk_index`, `content`, `section` (nullable), `details` (JSONB), `char_len`, `token_estimate`, `embedding` (`vector(embedding_dimensions)`), with `UNIQUE(document_id, chunk_index)`. The schema SHALL NOT reuse courier's `kb_documents`/`kb_chunks`.

#### Scenario: Duplicate chunk index in one document
- **WHEN** two chunks of the same document are written with the same `chunk_index`
- **THEN** the `UNIQUE(document_id, chunk_index)` constraint rejects the write

### Requirement: pgvector extension and cosine index via migration
An Alembic migration SHALL run `CREATE EXTENSION IF NOT EXISTS vector`, create both tables, and create an HNSW index on `chunks.embedding` using `vector_cosine_ops`. Schema SHALL be applied by migration, not `create_all`.

#### Scenario: Fresh database upgraded
- **WHEN** `alembic upgrade head` runs on an empty Postgres
- **THEN** the `vector` extension exists, both tables exist, and the HNSW cosine index is present on `chunks.embedding`

### Requirement: chunks.jsonl is the input contract
Ingest SHALL accept phase-1 `chunks.jsonl` records unchanged, mapping each field to a column and grouping records into documents by `source_uri` + `content_sha256`. The `embedding` column is populated by this phase; every other column comes from the record.

#### Scenario: A phase-1 export is loaded
- **WHEN** a `chunks.jsonl` produced by phase 1 is ingested
- **THEN** each record's fields land in the matching columns and its chunks are attached to one `documents` row per `source_uri`

### Requirement: Idempotent upsert keyed by identity and checksum
Ingest SHALL be idempotent. A document whose `source_uri` exists with the same `content_sha256` and complete chunks SHALL be skipped. When `content_sha256` differs, the document's existing chunks SHALL be deleted and the new chunks inserted in place. Re-running an unchanged ingest SHALL NOT create duplicate rows.

#### Scenario: Re-ingesting identical content
- **WHEN** the same file (same bytes) is ingested twice
- **THEN** the second run makes no new document or chunk rows

#### Scenario: Re-ingesting changed content
- **WHEN** a file's bytes change and it is re-ingested
- **THEN** its `documents` row's `content_sha256` updates and its old chunks are replaced by the new ones

### Requirement: A partially embedded document is not left "ready"
When any chunk of a document fails to embed, ingest SHALL NOT persist that document as complete; the failure SHALL surface and the run SHALL exit non-zero.

#### Scenario: One chunk cannot be embedded
- **WHEN** a document has a chunk that fails embedding after retries
- **THEN** the document is not committed as a complete, searchable set and the run reports failure
