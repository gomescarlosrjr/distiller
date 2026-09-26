# Design — distiller conversion pipeline

## Context

See proposal.md — Why. The constraints that shaped the approach:

- **A prior art exists.** terpafy-ai/courier already runs Docling → chunk → embed in production for its knowledge base. The chunking, PDF handling and index filtering are solved and battle-tested; the cost of reinventing them is pure risk.
- **Personal, offline-first tool.** distiller runs on Carlos's Mac for his own conversions, not as a cluster service. Whatever infrastructure a decision implies is a cost he pays alone.
- **Two stages people conflate.** *Extraction* (document → markdown) is Docling's job and is where "quality" lives; *embeddings* (text → vectors) is a separate, later concern. The stakeholder initially asked for Groq/Anthropic "embeddings"; the interview corrected this — neither vendor offers an embeddings API.
- **Docling's VLM API moves fast.** Its remote-VLM classes have changed module and shape between releases, so any code touching them is fragile.

Decisions below were taken by the stakeholder in a two-round planning interview on 2026-09-26 (engine / scope / embeddings / formats, then a follow-up on the VLM token's purpose).

## Goals / Non-Goals

**Goals:**
- Reuse courier's proven ingestion logic rather than reimplement it.
- Convert the formats Carlos named (PDF, EPUB, "other kinds") to clean Markdown.
- Produce an export that a later PG Vector phase can load without reshaping.
- Best-effort extraction quality with a lever for hard documents, without forcing infrastructure.

**Non-Goals:**
- Anything under proposal.md — Non-goals and Out of scope. At the design level additionally: no plugin system, no async job queue, no multi-user state.

## Decisions

Each row: the decision, the alternatives rejected, and why.

### How Docling runs

| Decision | Rejected | Why |
|---|---|---|
| **Local Docling library, in-process.** | (a) `docling-serve` via Docker Compose (courier's path, reuses its async 20-page-batch client); (b) selectable local + serve | The stakeholder chose local. It needs no Docker daemon, works offline, and is the least operational overhead for a one-person tool. The cost — PyTorch in the venv and whole-document memory use — is acceptable at personal scale, and page-batching is a documented follow-up if a large book ever OOMs. |

### Scope of the first version

| Decision | Rejected | Why |
|---|---|---|
| **Convert → chunk → export only; no database.** | full pipeline incl. PG Vector write + embeddings now | The stakeholder chose export-only. It delivers the immediate need (his own conversions) without standing up Postgres + pgvector + an embedding model, and lets the embedding-provider decision be made later on real data. The `chunks.jsonl` schema is built for the eventual INSERT so nothing is thrown away. |

### Extraction quality vs. embeddings

| Decision | Rejected | Why |
|---|---|---|
| **A Groq/Anthropic token is for VLM extraction, not embeddings.** | wire Groq/Anthropic as the embedding provider | Neither Groq nor Anthropic exposes an embeddings API. The stakeholder's real concern — *"I don't want worst extractions"* — is an extraction-fidelity problem, which a vision model solves at the *conversion* stage. This was corrected explicitly in the interview's second round. |
| **Embeddings deferred to Voyage or OpenAI (phase 2).** | pick an embedding provider now | Out of scope this phase, and the quality options are Voyage (Anthropic's recommended partner) or OpenAI — a decision better made when the DB exists. The export stays embedding-agnostic. |
| **Local Docling is the default; VLM is opt-in for page-image formats.** | VLM always on; VLM for every format | Born-digital DOCX/EPUB/HTML already convert with high fidelity through Docling's structured backends — sending them to a vision model adds cost and latency for no gain. VLM earns its place only on scanned/complex PDFs and images. |

### Formats

| Decision | Rejected | Why |
|---|---|---|
| **EPUB and non-PDF formats handled by Docling directly; no pandoc/ebooklib.** | add a pandoc/ebooklib EPUB→HTML fallback | The stakeholder asked for EPUB. Verified against Docling's supported-formats docs that EPUB (and DOCX/PPTX/XLSX/HTML/images/CSV/AsciiDoc) is native — so a fallback would be dead code. |

### Reliability

| Decision | Rejected | Why |
|---|---|---|
| **The VLM path is lazily imported and wrapped; failures raise `ConverterError` and never affect the local path.** | import VLM symbols at module load | Docling's VLM API differs across releases; a top-level import could crash app startup on a version bump. Isolating it means the default (local) engine is always available and a VLM mismatch is a clear, actionable message. |
| **The chunker never drops content; the pipeline owns index/TOC filtering and reports every drop.** | let the chunker filter silently | Inherited from courier's #231 lesson: silent removal is undebuggable. Filtering is a caller decision, and every filtered chunk is surfaced (UI report, CLI count, `DocumentResult.filtered`). |
| **Chunker is a vendored copy, attributed in its docstring.** | import from courier as a dependency | courier is a separate private repo with its own app dependencies (FastAPI, SQLAlchemy, LangGraph); depending on it would drag all of that in. A vendored, attributed copy of one dependency-free module is the smaller cost, at the price of manual reconciliation on future fixes. |
