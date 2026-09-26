# Tasks — distiller conversion pipeline

All tasks are complete; this change is retro-documented. Each task cites the evidence that closes it. Everything is on branch `feat/distiller-scaffold`, commit `5c3a32c`. Tests were run with `uv run pytest` (16 passed) and, without the heavy deps, with `uv run --no-project --with pytest --with pydantic-settings --with pandas python -m pytest` (also 16 passed).

## 1. Project scaffold

- [x] 1.1 Create the repo layout (`pyproject.toml`, `src/distiller/`, `app.py`, `tests/`, `.env.example`, `.gitignore`, `README.md`) as a uv-managed Python 3.12 project. Verified: `git ls-files` lists 15 tracked files; `.env`/`output/` are gitignored.
- [x] 1.2 Pin dependencies: `docling`, `streamlit`, `pydantic-settings`, `python-dotenv`, `pandas`, `pypdf`; dev `pytest`, `ruff`. Verified: `uv sync --extra dev` resolved and installed (docling, torch 2.14, streamlit).

## 2. Conversion (capability: conversion)

- [x] 2.1 Local Docling engine as the default, using only Docling's stable core API (`DocumentConverter`/`PdfFormatOption`/`PdfPipelineOptions`). Verified: `_build_local_converter` builds a `DocumentConverter`; smoke test constructed it and converted an HTML document to Markdown.
- [x] 2.2 Format detection + media-type mapping for PDF/EPUB/DOCX/PPTX/XLSX/HTML/images/MD/TXT/CSV/AsciiDoc. Verified: `MEDIA_TYPES` in `converter.py`; `media_type_for('book.epub') == 'application/epub+zip'`.
- [x] 2.3 Optional VLM engine via an OpenAI-compatible endpoint (Groq/Anthropic), applied only to page-image formats; born-digital formats always use the local backend. Verified: `_BORN_DIGITAL_SUFFIXES` gate + `use_vlm` computation in `convert_to_markdown`.
- [x] 2.4 VLM path is isolated and fail-safe: lazy imports, missing key → `ConverterError`, Docling VLM-API mismatch → `ConverterError` without touching the local path. Verified: `_build_vlm_converter` try/except; local path imports no VLM symbols.
- [x] 2.5 OCR is an opt-in local-engine flag. Verified: `PdfPipelineOptions(do_ocr=...)` wired from `settings.do_ocr`.
- [x] 2.6 Empty/blank extraction is an error, not a silent empty document. Verified: `convert_to_markdown` raises `ConverterError` when markdown is blank.

## 3. Chunking (capability: chunking)

- [x] 3.1 Vendor the courier chunker (`chunk_markdown`, `chunk_book`, `chunk_curated`, `is_index_like`, `extract_title`, `legal_refs`, helpers) with the source attributed in the module docstring. Verified: `src/distiller/chunker.py` header cites courier.
- [x] 3.2 Three profiles selectable, default from settings. Verified: `pipeline._split`; `test_profile_override`.
- [x] 3.3 Hard cap so no chunk exceeds `max_chunk_chars`, splitting at word boundaries. Verified: `test_chunk_markdown_hard_cap_never_exceeded`, `test_chunk_book_respects_cap`.
- [x] 3.4 `book` profile keeps pipe tables whole. Verified: `test_chunk_book_keeps_table_whole`.
- [x] 3.5 `curated` profile records `article`/`chapter` from headers. Verified: `test_chunk_curated_extracts_legal_refs`.
- [x] 3.6 Index/TOC classification is conservative and prose-safe. Verified: `test_is_index_like_detects_toc`, `test_is_index_like_rejects_prose`.

## 4. Pipeline (capability: chunking + export)

- [x] 4.1 sha256 the source bytes as the document identity; extract title (first `#` header, else filename stem). Verified: `test_process_document_basic` asserts sha256 and title.
- [x] 4.2 Index/TOC filtering is the pipeline's decision and every filtered chunk is reported, never silently dropped. Verified: `test_index_section_is_filtered_and_reported`, `test_filter_can_be_disabled`.
- [x] 4.3 Chunk indices are sequential and gap-free after filtering. Verified: `test_chunk_indices_are_sequential`.

## 5. Export (capability: export)

- [x] 5.1 Emit `<stem>.md` (full markdown) and `<stem>.chunks.jsonl` (one JSON object per line). Verified: `exporter.write_outputs`; `test_write_outputs`.
- [x] 5.2 JSONL record schema: `source_uri, content_sha256, media_type, title, chunk_index, content, section, details, char_len, token_estimate`, mirroring courier's document/chunk columns. Verified: `test_chunks_jsonl_roundtrip` asserts the exact key set and `details.chunk_profile`.

## 6. UI / CLI / config

- [x] 6.1 Streamlit app: multi-file upload, sidebar config, per-file preview (markdown + chunk table), filtered-chunk report, `.md`/`.jsonl` downloads, optional save to disk. Verified: `app.py` imports cleanly under the installed env.
- [x] 6.2 `distiller` CLI for batch conversion with `--profile`/`--out`. Verified: `src/distiller/cli.py`; registered as a `project.scripts` entry point.
- [x] 6.3 pydantic-settings config with `.env` support and per-provider VLM defaults. Verified: `src/distiller/config.py`, `.env.example`.

## 7. Verification of the whole

- [x] 7.1 `uv sync --extra dev` installs the full stack. Verified: install log shows docling + torch + streamlit.
- [x] 7.2 Real end-to-end conversion (not stubbed): an HTML document converts to Markdown, chunks, and writes both output files. Verified: smoke run produced 2 chunks, table kept whole, `demo.md` + `demo.chunks.jsonl`.
- [x] 7.3 Full test suite green. Verified: `16 passed` under both the installed env and the minimal offline env.
