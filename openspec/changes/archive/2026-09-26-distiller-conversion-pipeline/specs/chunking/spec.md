## Purpose

Splitting converted Markdown into retrieval-ready chunks — three selectable profiles, a guarantee that the chunker never drops content, table integrity, a hard size cap that protects the embedding context window, and a conservative index/TOC classifier the pipeline uses to filter noise.

## ADDED Requirements

### Requirement: Three chunk profiles, selectable
The chunker SHALL expose `generic` (`chunk_markdown`), `book` (`chunk_book`) and `curated` (`chunk_curated`) profiles, each returning `[{"content": str, "metadata": dict}]`. The pipeline selects the profile per document, defaulting to `default_chunk_profile` from settings.

#### Scenario: A per-run profile override
- **WHEN** `process_document` is called with an explicit `profile`
- **THEN** that profile's splitter is used and the result's `profile` records it

#### Scenario: No override
- **WHEN** `process_document` is called without a profile
- **THEN** `default_chunk_profile` (default `book`) is used

### Requirement: No chunk exceeds the hard cap
No emitted chunk SHALL exceed `max_chunk_chars` characters. Oversized content SHALL be split at word boundaries (`_hard_split`), falling back to a mid-word cut only for an unbroken run with no whitespace.

#### Scenario: An unbroken run longer than the cap
- **WHEN** a section contains a single whitespace-free run longer than `max_chunk_chars`
- **THEN** it is split into pieces each at most `max_chunk_chars` long, and no content is lost

#### Scenario: The book profile on long prose
- **WHEN** `chunk_book` runs on prose far larger than the cap
- **THEN** every produced chunk is at most `max_chunk_chars` long

### Requirement: The chunker never drops content
The chunker functions SHALL NOT discard content. Any exclusion of chunks (for example index/TOC filtering) is the caller's explicit decision, made observable by the caller, not performed silently inside the chunker.

#### Scenario: Splitting preserves all words
- **WHEN** a document is chunked
- **THEN** every word of the source Markdown appears in at least one chunk

### Requirement: Tables stay whole in the book profile
In the `book` profile, a Markdown pipe table SHALL be emitted as its own chunk and never cut mid-table; only a table larger than `max_chunk_chars` is split, and then by whole rows with the header/separator repeated (`_split_table`).

#### Scenario: A dose table inside a document
- **WHEN** `chunk_book` encounters a pipe table that fits within the cap
- **THEN** the entire table is one chunk with all its rows intact

### Requirement: The book profile carries overlap
In the `book` profile, each prose chunk after the first SHALL begin with a word-aligned tail (`_overlap_tail`) of the previous chunk, so a fact spanning a boundary is embedded whole at least once.

#### Scenario: Prose split across two chunks
- **WHEN** prose is packed into more than one chunk
- **THEN** the later chunk starts with the word-aligned tail of the earlier one

### Requirement: The curated profile records legal references
In the `curated` profile, when a section header names an article or chapter (`legal_refs`), the chunk metadata SHALL carry `article` and/or `chapter`.

#### Scenario: A header naming an article and chapter
- **WHEN** a curated section sits under "Capítulo V" with header "Art. 37"
- **THEN** its chunk metadata includes `article: "Art. 37"` and `chapter: "Capítulo V"`

### Requirement: Conservative index/TOC classification
`is_index_like` SHALL classify a chunk as index/TOC only when at least 5 non-blank lines are index-shaped (dot-leader page refs or short comma-separated page references) and those lines are at least 60% of the chunk, biasing against false positives so real prose is never flagged.

#### Scenario: A table-of-contents block
- **WHEN** a chunk is a run of dot-leader and page-reference lines
- **THEN** `is_index_like` returns true

#### Scenario: Ordinary prose with a decimal number
- **WHEN** a chunk is prose containing values like "1,2" or a trailing number
- **THEN** `is_index_like` returns false
