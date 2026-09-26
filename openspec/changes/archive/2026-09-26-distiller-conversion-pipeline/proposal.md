# distiller — document → Markdown → chunks conversion pipeline

> Retro-documented change. Everything below was built and verified on 2026-09-26 and is recorded here so the decisions outlive the session that made them. Evidence is cited as a commit SHA, file path, or test name — the repo is local (branch `feat/distiller-scaffold`), so there are no PRs yet.

## Why

Carlos wanted a service to turn documents into vector-ready text for a personal knowledge base. In the stakeholder's words: *"i wanna to create a service to convert .md file from courier called docling. … This services need to use Streamlit to upload pdf, epub or other kind of file and prepare it for Data base vector. Actually, i will use it for my own coversions, but as soon as possibile i will use to create my own PG Vector."*

The terpafy-ai `courier` repo already solved the hard parts of this for its Med/Grow knowledge base — a proven Docling → chunk → embed ingestion pipeline. Rather than reinvent it, distiller extracts and adapts that logic into a small, self-contained tool Carlos can run on his Mac:

- `courier:scripts/ingest_knowledge_base.py` — orchestration, PDF handling, index/TOC filtering.
- `courier:src/common/text_chunker.py` — three chunk profiles, table-aware splitting, hard-cap word-boundary splitting, index detection.
- `courier:src/common/config.py` — the pydantic-settings pattern.
- `courier:src/common/kb_manifest.py` — the document/chunk metadata shape the export mirrors.

The one deliberate divergence: courier runs Docling as a remote `docling-serve` microservice (to keep PyTorch out of its app image); distiller runs Docling as a **local library**, because it is a personal, offline-first tool where standing up a microservice is not worth it.

## What Changes

- **New repo `distiller`** under `~/Developer/myservices` — Python 3.12, uv, Streamlit UI + a `distiller` CLI.
- **Local Docling conversion** (`src/distiller/converter.py`): documents → Markdown in-process, no keys, offline. Supports every Docling-native format (PDF, EPUB, DOCX, PPTX, XLSX, HTML, images, CSV, AsciiDoc, Markdown).
- **Optional VLM extraction** for hard/scanned page-image formats, routed through an OpenAI-compatible endpoint (Groq or Anthropic). Isolated and fail-safe: a missing key or a Docling VLM-API mismatch raises a clear error and never affects the local path.
- **Chunking** (`src/distiller/chunker.py`, vendored from courier): `generic`, `book`, `curated` profiles; tables kept whole; hard cap so no chunk exceeds the embedding context window; index/TOC filtering that reports every dropped chunk.
- **PG-Vector-ready export** (`src/distiller/exporter.py`): `<name>.md` plus a `<name>.chunks.jsonl` whose row schema mirrors courier's `kb_documents` + `kb_chunks`, so a later `INSERT` is straightforward.
- **Tests** (`tests/`): 16 tests, offline (the converter is stubbed), covering the chunker, the pipeline, filtering, and the export schema.

## In scope

| Area | What is in | Evidence |
|---|---|---|
| Conversion | Local Docling engine (default) + optional Groq/Anthropic VLM; format detection; OCR toggle; empty-output guard | `src/distiller/converter.py`; end-to-end HTML conversion verified |
| Chunking | `generic`/`book`/`curated` profiles, table-aware, hard cap, index detection | `src/distiller/chunker.py`; `tests/test_chunker.py` (9 tests) |
| Pipeline | sha256 identity, title extraction, profile selection, index filtering with reporting | `src/distiller/pipeline.py`; `tests/test_pipeline.py` |
| Export | `<name>.md` + `<name>.chunks.jsonl` with the fixed record schema | `src/distiller/exporter.py`; `test_chunks_jsonl_roundtrip`, `test_write_outputs` |
| UI / CLI | Streamlit upload/convert/preview/download; `distiller` CLI for batch | `app.py`, `src/distiller/cli.py` |
| Config | pydantic-settings for engine, VLM provider/keys, chunk profile, cap, filter, output dir | `src/distiller/config.py`, `.env.example` |
| Repo state | Scaffolded, installed (`uv sync`), tests green, committed on `feat/distiller-scaffold` | commit `5c3a32c` |

## Out of scope

- **PG Vector write + embeddings.** The export schema is built for it, but no database, no embedding generation, no upsert. This is phase 2 (see Non-goals for the provider constraint).
- **Large-PDF page batching.** courier splits PDFs into 20-page batches (`_pdf_batches`) so a whole book never sits in the converter at once. distiller's local engine loads a document whole; batching is a documented follow-up if memory becomes a problem.
- **Med manifest / domain metadata.** courier's `kb_manifest.py` (domains, citation metadata, legal status) is not ported; distiller derives title from the document and profile from settings.
- **Pushing the repo / opening a PR.** The repo is local only.
- **Moving distiller under terpafy-ai.** It stays personal for now; these specs live here, not in axiom.

## Non-goals

- Running Docling as a microservice. Local library only (the deliberate divergence from courier).
- Using Groq or Anthropic for **embeddings** — neither offers an embeddings API. When phase 2 arrives, embeddings use **Voyage** (Anthropic's recommended partner) or **OpenAI**. Groq/Anthropic here are for VLM **extraction** only.
- Pixel-level Streamlit polish; the UI is a functional front end over the pipeline.
- Silent content loss anywhere — a dropped chunk is always reported, an empty extraction is always an error.

## Capabilities

### New Capabilities

- `conversion`: turning an uploaded document into Markdown — the local Docling engine, the optional isolated VLM engine, supported formats, OCR, and the empty-output guard.
- `chunking`: splitting Markdown into retrieval-ready chunks — the three profiles, the never-drop guarantee, table integrity, the hard cap, and index/TOC classification.
- `export`: the two artifacts a converted document yields — the full Markdown and the PG-Vector-ready `chunks.jsonl` record schema.

### Modified Capabilities

None — this store had no specs before this change.

## Impact

- **distiller**: `src/distiller/{converter,chunker,pipeline,exporter,config,cli}.py`, `app.py`, `tests/`, `pyproject.toml`, `.env.example`. Docling pulls PyTorch + model weights (downloaded lazily on first PDF/OCR/VLM run).
- **Dependency on courier**: the chunker is a vendored copy of `courier:src/common/text_chunker.py`. A future fix on either side is a manual reconciliation, not a shared package.
- **Roadmap**: phase 2 (PG Vector + embeddings) consumes the `chunks.jsonl` this change produces; the record schema is the contract between the two phases.
