## Purpose

Turning an uploaded document into Markdown via Docling: a local in-process engine as the default and an optional, isolated remote-VLM engine for hard page-image documents, with format detection, OCR control, and a guard against silent empty output.

## ADDED Requirements

### Requirement: Local extraction is the default
The service SHALL convert documents with a local, in-process Docling pipeline by default, requiring no API keys and no network. The engine is selected by `extraction_engine` (`local` | `vlm`) in `src/distiller/config.py`, defaulting to `local`.

#### Scenario: No configuration is provided
- **WHEN** a document is converted with default settings
- **THEN** it is converted by the local Docling engine (`converter._build_local_converter`) with no external calls

#### Scenario: The local engine uses only Docling's stable core API
- **WHEN** the local converter is built
- **THEN** it imports only `DocumentConverter`, `PdfFormatOption` and `PdfPipelineOptions`, and no VLM symbols, so a change in Docling's VLM API cannot affect it

### Requirement: Docling-native input formats
The service SHALL accept the formats Docling converts natively — PDF, EPUB, DOCX, PPTX, XLSX, HTML/XHTML, images (PNG/JPEG/TIFF/BMP/WEBP), Markdown, plain text, CSV and AsciiDoc — and record a media type per source suffix (`converter.MEDIA_TYPES`). No pandoc/ebooklib fallback is used.

#### Scenario: An EPUB is uploaded
- **WHEN** a `.epub` file is converted
- **THEN** Docling's native EPUB backend produces Markdown and the exported media type is `application/epub+zip`

#### Scenario: An unknown suffix is uploaded
- **WHEN** a file with an unrecognized suffix is converted
- **THEN** its media type falls back to `application/octet-stream` and conversion is still attempted

### Requirement: Optional VLM extraction for page-image formats
When `extraction_engine` is `vlm`, the service SHALL route page-image formats (PDF, images) through a remote OpenAI-compatible `/v1/chat/completions` endpoint (Groq or Anthropic) via Docling's API-VLM pipeline. Born-digital formats (DOCX, EPUB, HTML, Markdown, TXT, CSV, AsciiDoc — `converter._BORN_DIGITAL_SUFFIXES`) SHALL always use the local structured backend, even under the VLM engine.

#### Scenario: A scanned PDF under the VLM engine
- **WHEN** a `.pdf` is converted with `extraction_engine = vlm`
- **THEN** its pages are sent to the configured provider's endpoint and model (`config.resolved_endpoint()` / `resolved_model()`)

#### Scenario: A DOCX under the VLM engine
- **WHEN** a `.docx` is converted with `extraction_engine = vlm`
- **THEN** it is still converted locally, because its structured backend is already high-fidelity

### Requirement: The VLM path is isolated and fails safe
The VLM engine SHALL be constructed with lazy imports inside `converter._build_vlm_converter`. A missing provider API key SHALL raise `ConverterError` before any conversion. An incompatibility with the installed Docling's VLM API SHALL raise `ConverterError` with guidance and SHALL NOT affect the local engine.

#### Scenario: VLM selected without a key
- **WHEN** `extraction_engine = vlm` and the selected provider's key is empty
- **THEN** conversion raises `ConverterError` naming the missing key

#### Scenario: Installed Docling's VLM API differs
- **WHEN** building the VLM converter fails on an import or signature mismatch
- **THEN** a `ConverterError` explains that the local engine is unaffected and the version should be pinned or the builder adjusted

### Requirement: OCR is an opt-in local flag
Local-engine OCR SHALL be controlled by `do_ocr` (default off) and passed to `PdfPipelineOptions(do_ocr=...)`.

#### Scenario: OCR left at its default
- **WHEN** a born-digital PDF is converted with defaults
- **THEN** OCR is not run and the PDF's own text layer is extracted

### Requirement: Empty extraction is an error
When conversion yields blank or whitespace-only Markdown, the service SHALL raise `ConverterError` rather than return an empty document, and the message SHALL suggest OCR or the VLM engine.

#### Scenario: An image-only PDF with OCR off
- **WHEN** a scanned PDF is converted by the local engine with OCR off and no text is extracted
- **THEN** conversion raises `ConverterError` pointing to OCR or the VLM engine
