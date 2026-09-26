# distiller

Convert documents (PDF, EPUB, DOCX, PPTX, XLSX, HTML, images, …) into clean
**Markdown** and split them into **retrieval-ready chunks**, ready to load into a
PG Vector database. Built on [Docling](https://github.com/docling-project/docling),
with a Streamlit UI.

Local-first: Docling runs in-process, offline, no API keys required. For
hard/scanned/complex pages you can optionally route page images through a remote
vision model (**Groq** or **Anthropic**) for higher extraction fidelity.

The chunking (three profiles, table-aware splitting, index/TOC filtering) is
vendored from Terpafy's `courier` knowledge-base pipeline, so it matches what
already works in production there.

## Status

**v1 = convert → chunk → export.** No database writes yet. The exported
`chunks.jsonl` is shaped so the PG Vector phase is a straight `INSERT` (add an
`embedding` column then).

## Requirements

- Python 3.12
- [`uv`](https://docs.astral.sh/uv/)
- First run downloads Docling's layout/OCR model weights (a few hundred MB).

## Setup

```bash
cd distiller
uv sync                      # installs Docling, Streamlit, etc.
cp .env.example .env         # optional — all defaults are safe
```

## Run the app

```bash
uv run streamlit run app.py
```

Upload files, pick the engine/profile in the sidebar, click **Convert**, then
download the `.md` and `.chunks.jsonl`.

## Run from the CLI

```bash
uv run distiller path/to/book.pdf notes.epub --profile book --out output/
```

## Configuration (`.env`)

| Key | Default | Meaning |
| --- | --- | --- |
| `EXTRACTION_ENGINE` | `local` | `local` (in-process) or `vlm` (remote vision model) |
| `DO_OCR` | `false` | Local OCR for scanned PDFs/images |
| `VLM_PROVIDER` | `groq` | `groq` or `anthropic` (VLM engine only) |
| `GROQ_API_KEY` / `ANTHROPIC_API_KEY` | — | Key for the chosen VLM provider |
| `VLM_ENDPOINT` / `VLM_MODEL` | per-provider | Override the OpenAI-compatible endpoint/model |
| `DEFAULT_CHUNK_PROFILE` | `book` | `book`, `curated`, or `generic` |
| `MAX_CHUNK_CHARS` | `2000` | Hard cap per chunk (~500 tokens) |
| `FILTER_INDEX_CHUNKS` | `true` | Drop index/TOC chunks (always reported, never silent) |
| `OUTPUT_DIR` | `./output` | Where CLI / "save to disk" writes |

### Extraction engines

- **local** — Docling's structured backends + optional OCR. Best for born-digital
  PDFs, DOCX, EPUB, HTML. Fast, free, offline.
- **vlm** — routes **page-image** formats (PDF, images) through a remote vision
  model via Docling's API-VLM pipeline. Born-digital formats (DOCX/EPUB/HTML/…)
  always use the local structured backend, since it's already high-fidelity there.
  - Neither Groq nor Anthropic provides embeddings — the VLM here is used purely
    to improve **extraction** quality.
  - Anthropic is reached via its OpenAI-compatible `/v1/chat/completions` endpoint
    (beta); Groq is natively OpenAI-compatible.

> Docling's VLM API surface has changed between releases. `converter.py` builds it
> defensively and, if your installed version's API differs, raises a clear error
> **without affecting the local engine**. Pin a compatible `docling` in
> `pyproject.toml` if needed.

### Chunk profiles

- **book** — whole documents: paragraph packing (~400 tok) with ~80-tok overlap,
  pipe tables kept whole. Default.
- **curated** — hand-written structured markdown: header-aware, ~600 tok, no
  overlap; records `article`/`chapter` from headers when present.
- **generic** — header/paragraph aware with overlap.

## Export schema (`<name>.chunks.jsonl`)

One JSON object per line:

```json
{
  "source_uri": "handbook.pdf",
  "content_sha256": "…",
  "media_type": "application/pdf",
  "title": "Handbook of Cannabis",
  "chunk_index": 0,
  "content": "…",
  "section": "1. Introduction",
  "details": {"chunk_profile": "book"},
  "char_len": 1584,
  "token_estimate": 396
}
```

## Tests

```bash
uv run pytest
```

Tests stub the converter, so they run offline (no Docling, no network, no model
downloads).

## Roadmap

- **Phase 2 — PG Vector**: embed chunks (Voyage or OpenAI — Anthropic recommends
  Voyage; neither Groq nor Anthropic offers embeddings) and `INSERT` into Postgres
  + `pgvector`. The export schema already carries the document/chunk columns.
- Large-PDF page batching (port courier's 20-page `pypdf` split) if you hit memory
  limits on big books with the local engine.

## Project layout

```
distiller/
├── app.py                    # Streamlit UI
├── src/distiller/
│   ├── config.py             # pydantic-settings
│   ├── converter.py          # Docling wrapper (local | VLM)
│   ├── chunker.py            # vendored from courier
│   ├── pipeline.py           # convert → chunk → records
│   ├── exporter.py           # markdown + chunks.jsonl
│   └── cli.py                # `distiller` command
└── tests/
```
