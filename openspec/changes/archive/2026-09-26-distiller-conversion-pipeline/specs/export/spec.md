## Purpose

The two artifacts a converted document yields — the full Markdown and a PG-Vector-ready `chunks.jsonl` — plus the record schema, document identity, and sequential indexing that let a later PG Vector phase load the output without reshaping it.

## ADDED Requirements

### Requirement: Two output artifacts per document
For each converted document the service SHALL produce `<stem>.md` (the full Markdown) and `<stem>.chunks.jsonl` (one JSON object per chunk, newline-delimited). `write_outputs` writes both under `output_dir`; the Streamlit app and CLI offer them as downloads.

#### Scenario: A document is exported to disk
- **WHEN** `write_outputs(result, dir)` runs
- **THEN** `<stem>.md` holds the full Markdown and `<stem>.chunks.jsonl` holds one line per chunk

### Requirement: Fixed chunk record schema
Each JSONL line SHALL be a JSON object with exactly these keys: `source_uri`, `content_sha256`, `media_type`, `title`, `chunk_index`, `content`, `section`, `details`, `char_len`, `token_estimate`. The columns mirror courier's `kb_documents` + `kb_chunks` so a later `INSERT` needs no reshaping.

#### Scenario: A record is read back
- **WHEN** a line of `chunks.jsonl` is parsed
- **THEN** its key set is exactly those ten fields and `details.chunk_profile` names the profile that produced it

### Requirement: Document identity by content hash
Every chunk of a document SHALL carry `content_sha256`, the SHA-256 of the source file bytes, as the stable document identity for a future idempotent upsert. `source_uri` SHALL be the source file name.

#### Scenario: The same file is exported twice
- **WHEN** identical source bytes are processed on two runs
- **THEN** both runs produce the same `content_sha256` for the document's chunks

### Requirement: Sequential, gap-free chunk indices
`chunk_index` SHALL number a document's exported chunks from 0 with no gaps, assigned after index/TOC filtering so the exported sequence is contiguous.

#### Scenario: Some chunks are filtered
- **WHEN** a document has index/TOC chunks removed
- **THEN** the remaining chunks are still numbered 0..n-1 with no missing indices

### Requirement: The schema is embedding-agnostic
The export SHALL NOT include embeddings or a vector column. Generating embeddings and writing to PG Vector are out of scope for this capability; the record schema is the contract the later phase extends (adding an embedding column).

#### Scenario: A downstream loader adds vectors
- **WHEN** the PG Vector phase loads a `chunks.jsonl`
- **THEN** it computes embeddings itself (Voyage or OpenAI) and inserts them alongside the existing fields, which it does not have to reshape
