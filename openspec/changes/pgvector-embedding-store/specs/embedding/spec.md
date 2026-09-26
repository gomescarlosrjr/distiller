## Purpose

Turning chunk text into vectors: a provider-agnostic embedder with a Voyage `voyage-3` implementation, input-type awareness, batching, retry with backoff, a pinned dimension, and a fail-loud contract so no chunk is silently lost.

## ADDED Requirements

### Requirement: Provider-agnostic embedder interface
The service SHALL define an `Embedder` interface with `embed_documents(texts)` and `embed_query(text)`. Ingestion and retrieval SHALL depend on this interface, not on a concrete provider SDK, so a different provider is a drop-in and tests can use a fake embedder without a network.

#### Scenario: Tests run without network
- **WHEN** the pipeline is tested
- **THEN** a fake `Embedder` is injected and no external embedding call is made

### Requirement: Voyage voyage-3 implementation
A `VoyageEmbedder` SHALL call Voyage's `voyage-3` model using `VOYAGE_API_KEY`, return vectors of `embedding_dimensions` (default 1024), and SHALL declare `input_type="document"` when embedding chunks for storage and `input_type="query"` when embedding a search query.

#### Scenario: Embedding chunks for storage
- **WHEN** chunks are embedded during ingestion
- **THEN** the request uses `input_type="document"`

#### Scenario: Embedding a search query
- **WHEN** a query is embedded for retrieval
- **THEN** the request uses `input_type="query"`

### Requirement: Batched requests
The embedder SHALL send document texts in batches of at most `embed_batch_size`, preserving order, so a large document is embedded in bounded requests.

#### Scenario: More chunks than the batch size
- **WHEN** a document has more chunks than `embed_batch_size`
- **THEN** they are embedded across multiple requests and the returned vectors align 1:1 with the input order

### Requirement: Retry then fail loud
Transient embedding failures SHALL be retried with exponential backoff up to a fixed cap. After the cap the embedder SHALL raise, and the caller SHALL fail the affected document rather than store it partially — a run that dropped any chunk exits non-zero.

#### Scenario: Retries are exhausted
- **WHEN** embedding a chunk keeps failing past the retry cap
- **THEN** the embedder raises, the document is not marked stored/ready, and the process outcome is non-zero

### Requirement: Dimension guard
The embedder SHALL verify that each returned vector has length `embedding_dimensions` and SHALL raise on a mismatch, so a model/config drift cannot write wrong-width vectors into a `vector(1024)` column.

#### Scenario: A vector of the wrong width
- **WHEN** a returned embedding does not have `embedding_dimensions` values
- **THEN** the embedder raises rather than returning it
