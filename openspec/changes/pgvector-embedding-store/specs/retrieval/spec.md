## Purpose

Cosine similarity search over the vector store, returning chunks with the metadata needed to cite them and a score — the stable interface a future LangGraph agent will consume as a tool.

## ADDED Requirements

### Requirement: Similarity search returns chunks with citation metadata
The service SHALL provide `search(query, top_k=5, filters=None)` that embeds `query` with `input_type="query"`, ranks stored chunks by cosine distance, and returns at most `top_k` results, each carrying `content`, `source_uri`, `section`, `details` and a similarity `score`. Results SHALL be plain data (not ORM rows tied to a session).

#### Scenario: A query matches a stored chunk
- **WHEN** `search` is called with a query semantically close to a stored chunk
- **THEN** that chunk is returned near the top with its `source_uri`, `section`, `details` and score

#### Scenario: Fewer matches than requested
- **WHEN** the store holds fewer chunks than `top_k`
- **THEN** all available chunks are returned, ranked, without error

### Requirement: Metadata filters restrict candidates before ranking
`search` SHALL accept optional filters (for example `source_uri` or a `details` field) and apply them in SQL so ranking runs over the filtered candidate set, not a post-filtered fixed top-k.

#### Scenario: Restricting to one document
- **WHEN** `search` is called with a `source_uri` filter
- **THEN** only chunks from that document are ranked and returned

### Requirement: Query and document embeddings use matching roles
The query SHALL be embedded with `input_type="query"` while stored vectors were written with `input_type="document"`, so retrieval uses the asymmetric pair the model expects.

#### Scenario: A query is embedded for search
- **WHEN** `search` embeds its query
- **THEN** it uses the query input type, distinct from the document type used at ingest

### Requirement: Stable interface for a future agent tool
`search` SHALL be a documented, stable function usable directly by a later LangGraph tool, without the caller touching the store's session or ORM internals. Building the agent is out of scope for this capability.

#### Scenario: An agent tool wraps retrieval
- **WHEN** a future LangGraph tool needs knowledge-base search
- **THEN** it calls `search(query, top_k, filters)` and receives citation-ready results, with no dependency on store internals
