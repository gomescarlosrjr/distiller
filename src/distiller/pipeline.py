"""Orchestration: document bytes -> Markdown -> retrieval-ready chunk records.

Adapted from terpafy-ai/courier's ``ingest_file`` flow, minus the database. The
index/TOC filtering contract is preserved: filtered chunks are *reported*, never
silently dropped.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from . import chunker
from .config import ChunkProfile, Settings
from .converter import convert_to_markdown


@dataclass(frozen=True)
class ChunkRecord:
    """One chunk, shaped for a later PG Vector INSERT (embedding added in phase 2)."""

    source_uri: str
    content_sha256: str
    media_type: str
    title: str
    chunk_index: int
    content: str
    section: str | None
    details: dict[str, Any]
    char_len: int
    token_estimate: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_uri": self.source_uri,
            "content_sha256": self.content_sha256,
            "media_type": self.media_type,
            "title": self.title,
            "chunk_index": self.chunk_index,
            "content": self.content,
            "section": self.section,
            "details": self.details,
            "char_len": self.char_len,
            "token_estimate": self.token_estimate,
        }


@dataclass(frozen=True)
class FilteredChunk:
    """An index/TOC-style chunk excluded from the export (kept for reporting)."""

    section: str | None
    preview: str


@dataclass
class DocumentResult:
    """Everything one converted document produced."""

    source_uri: str
    title: str
    media_type: str
    content_sha256: str
    markdown: str
    profile: str
    chunks: list[ChunkRecord] = field(default_factory=list)
    filtered: list[FilteredChunk] = field(default_factory=list)


def _split(profile: ChunkProfile, markdown: str, max_chunk_chars: int) -> list[dict[str, Any]]:
    if profile is ChunkProfile.BOOK:
        return chunker.chunk_book(markdown, max_chunk_chars)
    if profile is ChunkProfile.CURATED:
        return chunker.chunk_curated(markdown, max_chunk_chars)
    return chunker.chunk_markdown(markdown, max_chunk_size=max_chunk_chars)


def _details(profile: ChunkProfile, metadata: dict[str, Any]) -> dict[str, Any]:
    """Chunk details: the profile plus any article/chapter a header named."""
    details: dict[str, Any] = {"chunk_profile": profile.value}
    for key in ("article", "chapter"):
        if metadata.get(key):
            details[key] = metadata[key]
    return details


def process_document(
    filename: str,
    data: bytes,
    settings: Settings,
    profile: ChunkProfile | None = None,
) -> DocumentResult:
    """Convert one document and split it into chunk records.

    Args:
        filename: Original file name — the chunk's stable ``source_uri``.
        data: Raw file bytes.
        settings: Effective settings (engine, OCR, chunk cap, index filter).
        profile: Chunk profile override; falls back to ``default_chunk_profile``.

    Raises:
        ConverterError: when Docling cannot produce usable Markdown.
    """
    source_uri = PurePosixPath(filename).name
    profile = profile or settings.default_chunk_profile
    content_sha256 = hashlib.sha256(data).hexdigest()

    markdown, media_type = convert_to_markdown(filename, data, settings)
    title = chunker.extract_title(markdown) or PurePosixPath(source_uri).stem

    raw_chunks = _split(profile, markdown, settings.max_chunk_chars)

    records: list[ChunkRecord] = []
    filtered: list[FilteredChunk] = []
    index = 0
    for chunk in raw_chunks:
        content = chunk["content"]
        metadata = chunk["metadata"]
        section = metadata.get("header") or None
        if settings.filter_index_chunks and chunker.is_index_like(content):
            filtered.append(FilteredChunk(section=section, preview=content[:120]))
            continue
        records.append(
            ChunkRecord(
                source_uri=source_uri,
                content_sha256=content_sha256,
                media_type=media_type,
                title=title,
                chunk_index=index,
                content=content,
                section=section,
                details=_details(profile, metadata),
                char_len=len(content),
                token_estimate=len(content) // chunker.CHARS_PER_TOKEN,
            )
        )
        index += 1

    return DocumentResult(
        source_uri=source_uri,
        title=title,
        media_type=media_type,
        content_sha256=content_sha256,
        markdown=markdown,
        profile=profile.value,
        chunks=records,
        filtered=filtered,
    )
