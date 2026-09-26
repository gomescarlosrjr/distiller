"""Docling wrapper: document bytes -> Markdown.

Two paths:

- **local** (default): Docling runs in-process. Uses only Docling's stable core
  API (``DocumentConverter`` / ``PdfFormatOption`` / ``PdfPipelineOptions``),
  which is unchanged across recent releases, so it works offline and never
  depends on the fast-moving VLM API surface.
- **vlm** (optional): routes page images through a remote OpenAI-compatible
  vision model (Groq or Anthropic) for best-quality extraction of hard/scanned/
  complex PDFs and images. All VLM imports are lazy and wrapped, so a Docling
  version whose VLM API differs raises a clear, actionable error instead of
  breaking the local path or crashing app startup.
"""

from __future__ import annotations

import zipfile
from io import BytesIO

from .config import ExtractionEngine, Settings

# Media type per suffix, so the export row records what the source was.
MEDIA_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".epub": "application/epub+zip",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".html": "text/html",
    ".htm": "text/html",
    ".xhtml": "application/xhtml+xml",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".adoc": "text/asciidoc",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
}

# Formats that carry a native text/structure layer — Docling's structured
# backend already gives high-fidelity markdown, so VLM routing is skipped for
# them even when the engine is "vlm" (VLM only helps page-image formats).
_BORN_DIGITAL_SUFFIXES = frozenset(
    {".epub", ".docx", ".doc", ".pptx", ".xlsx", ".html", ".htm", ".xhtml", ".md", ".txt", ".csv", ".adoc"}
)

_VLM_PROMPT = (
    "Convert this page to clean, faithful GitHub-flavored Markdown. Preserve "
    "headings, lists, and tables (as Markdown pipe tables). Do not summarize, "
    "translate, or omit content. Output only the Markdown."
)


class ConverterError(RuntimeError):
    """Raised when conversion fails for a reason worth showing the user."""


def media_type_for(filename: str) -> str:
    suffix = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    return MEDIA_TYPES.get(suffix, "application/octet-stream")


def _suffix(filename: str) -> str:
    return ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""


def _normalize_epub(data: bytes) -> bytes:
    """Repackage an EPUB so its ``mimetype`` entry is first and stored uncompressed.

    Docling detects an EPUB stream only through the ``filetype`` library, which
    recognizes the format only when the archive begins with an uncompressed
    ``mimetype`` member equal to ``application/epub+zip`` — the EPUB spec's rule.
    Many real EPUBs violate it (the member is compressed or not first), and
    Docling's generic-zip fallback special-cases Office/ODF but not EPUB, so the
    file is misread as ``application/zip`` and no format is chosen. Rewriting the
    archive fixes detection without altering any content. A non-zip or non-EPUB
    input is returned unchanged.
    """
    try:
        with zipfile.ZipFile(BytesIO(data)) as zin:
            names = zin.namelist()
            if "mimetype" not in names:
                return data
            mimetype = zin.read("mimetype").strip()
            if not mimetype.startswith(b"application/epub+zip"):
                return data
            out = BytesIO()
            with zipfile.ZipFile(out, "w") as zout:
                zout.writestr("mimetype", b"application/epub+zip", compress_type=zipfile.ZIP_STORED)
                for item in zin.infolist():
                    if item.filename == "mimetype":
                        continue
                    zout.writestr(item, zin.read(item.filename), compress_type=zipfile.ZIP_DEFLATED)
            return out.getvalue()
    except zipfile.BadZipFile:
        return data


def _build_local_converter(do_ocr: bool):
    """A DocumentConverter using Docling's stable in-process pipeline."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    pdf_options = PdfPipelineOptions(do_ocr=do_ocr)
    # Only PDF needs an explicit option (OCR); every other format falls back to
    # Docling's default backend.
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options)}
    )


def _build_vlm_converter(settings: Settings):
    """A DocumentConverter that routes PDF/image pages through a remote VLM.

    Isolated and defensively imported: raises ConverterError with guidance if
    the installed Docling exposes a different VLM API, so the (default) local
    path is never affected.
    """
    api_key = settings.resolved_api_key()
    if not api_key:
        raise ConverterError(
            f"VLM engine selected but no API key for provider "
            f"'{settings.vlm_provider.value}'. Set the key in .env."
        )

    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import VlmPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.pipeline.vlm_pipeline import VlmPipeline

        # ResponseFormat / ApiVlmOptions moved modules between releases; try the
        # locations Docling has used, newest first.
        try:
            from docling.datamodel.pipeline_options_vlm_model import (
                ApiVlmOptions,
                ResponseFormat,
            )
        except ImportError:  # older layout
            from docling.datamodel.pipeline_options import (  # type: ignore
                ApiVlmOptions,
                ResponseFormat,
            )

        api_options = ApiVlmOptions(
            url=settings.resolved_endpoint(),
            headers={"Authorization": f"Bearer {api_key}"},
            params={"model": settings.resolved_model()},
            prompt=_VLM_PROMPT,
            timeout=120,
            scale=1.0,
            response_format=ResponseFormat.MARKDOWN,
        )
        pipeline_options = VlmPipelineOptions(enable_remote_services=True)
        pipeline_options.vlm_options = api_options

        return DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_cls=VlmPipeline, pipeline_options=pipeline_options
                ),
                InputFormat.IMAGE: PdfFormatOption(
                    pipeline_cls=VlmPipeline, pipeline_options=pipeline_options
                ),
            }
        )
    except ConverterError:
        raise
    except Exception as exc:  # ImportError, TypeError from a shifted API, etc.
        raise ConverterError(
            "Could not configure Docling's VLM pipeline with the installed "
            f"docling version ({exc!r}). Pin a compatible docling in "
            "pyproject.toml or adjust converter._build_vlm_converter to match "
            "your version's VLM API. The local engine is unaffected."
        ) from exc


def convert_to_markdown(
    filename: str, data: bytes, settings: Settings
) -> tuple[str, str]:
    """Convert one uploaded document to Markdown.

    Args:
        filename: Original file name (drives format detection and media type).
        data: Raw file bytes.
        settings: Effective settings (engine, OCR, VLM provider/keys).

    Returns:
        ``(markdown, media_type)``.

    Raises:
        ConverterError: on an unusable file or a VLM configuration/runtime error.
    """
    from docling.datamodel.base_models import DocumentStream

    # Docling's stream-based EPUB detection is brittle (see _normalize_epub);
    # repackage so the format is recognized.
    if _suffix(filename) == ".epub":
        data = _normalize_epub(data)

    use_vlm = (
        settings.extraction_engine is ExtractionEngine.VLM
        and _suffix(filename) not in _BORN_DIGITAL_SUFFIXES
    )

    try:
        converter = (
            _build_vlm_converter(settings) if use_vlm else _build_local_converter(settings.do_ocr)
        )
        source = DocumentStream(name=filename, stream=BytesIO(data))
        result = converter.convert(source)
        markdown = result.document.export_to_markdown()
    except ConverterError:
        raise
    except Exception as exc:
        raise ConverterError(f"Docling failed to convert {filename!r}: {exc}") from exc

    if not markdown or not markdown.strip():
        raise ConverterError(
            f"No text extracted from {filename!r} "
            "(blank, or an image-only PDF — try enabling OCR or the VLM engine)."
        )
    return markdown, media_type_for(filename)
