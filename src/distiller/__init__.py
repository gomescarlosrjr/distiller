"""distiller — documents → Markdown → retrieval-ready chunks, via Docling."""

from .config import ChunkProfile, ExtractionEngine, Settings, VlmProvider, get_settings
from .converter import ConverterError, convert_to_markdown, media_type_for
from .exporter import chunks_jsonl, write_outputs
from .pipeline import ChunkRecord, DocumentResult, FilteredChunk, process_document

__all__ = [
    "ChunkProfile",
    "ChunkRecord",
    "ConverterError",
    "DocumentResult",
    "ExtractionEngine",
    "FilteredChunk",
    "Settings",
    "VlmProvider",
    "chunks_jsonl",
    "convert_to_markdown",
    "get_settings",
    "media_type_for",
    "process_document",
    "write_outputs",
]
