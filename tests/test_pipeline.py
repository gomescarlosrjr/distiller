"""Pipeline + exporter tests. The converter is stubbed, so these run offline
(no Docling import, no network, no model downloads)."""

import hashlib
import json

import pytest

from distiller import exporter, pipeline
from distiller.config import ChunkProfile, Settings

SAMPLE_MD = """# Handbook of Cannabis

## Introduction

Cannabis has a long history of medical use. This section introduces the topic
with enough prose to make at least one chunk of real content for the pipeline.

## Index

Aeroponics, 217
Nutrients, 45, 88-91
Dosing ......... 12
Interactions ......... 34
Compliance ......... 56
Appendix ......... 78
"""


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,  # ignore any local .env during tests
        DEFAULT_CHUNK_PROFILE="book",
        MAX_CHUNK_CHARS=2000,
        FILTER_INDEX_CHUNKS=True,
    )


@pytest.fixture(autouse=True)
def stub_converter(monkeypatch):
    def fake_convert(filename, data, settings):
        return SAMPLE_MD, "application/pdf"

    monkeypatch.setattr(pipeline, "convert_to_markdown", fake_convert)


def test_process_document_basic(settings):
    data = b"%PDF-1.7 fake bytes"
    result = pipeline.process_document("handbook.pdf", data, settings)

    assert result.source_uri == "handbook.pdf"
    assert result.title == "Handbook of Cannabis"
    assert result.media_type == "application/pdf"
    assert result.content_sha256 == hashlib.sha256(data).hexdigest()
    assert result.profile == "book"
    assert result.chunks, "expected at least one content chunk"


def test_chunk_indices_are_sequential(settings):
    result = pipeline.process_document("handbook.pdf", b"x", settings)
    assert [c.chunk_index for c in result.chunks] == list(range(len(result.chunks)))


def test_index_section_is_filtered_and_reported(settings):
    # The generic (header-based) profile puts the "## Index" block in its own
    # chunk, so the index heuristic has a standalone chunk to catch.
    result = pipeline.process_document(
        "handbook.pdf", b"x", settings, profile=ChunkProfile.GENERIC
    )
    # The TOC-shaped block is excluded from chunks but reported in `filtered`.
    assert result.filtered, "index block should be reported, not silently dropped"
    assert all("Aeroponics, 217" not in c.content for c in result.chunks)


def test_filter_can_be_disabled(settings):
    settings = settings.model_copy(update={"filter_index_chunks": False})
    result = pipeline.process_document(
        "handbook.pdf", b"x", settings, profile=ChunkProfile.GENERIC
    )
    assert not result.filtered
    assert any("Aeroponics, 217" in c.content for c in result.chunks)


def test_profile_override(settings):
    result = pipeline.process_document(
        "handbook.pdf", b"x", settings, profile=ChunkProfile.GENERIC
    )
    assert result.profile == "generic"


def test_chunks_jsonl_roundtrip(settings):
    result = pipeline.process_document("handbook.pdf", b"x", settings)
    text = exporter.chunks_jsonl(result)
    rows = [json.loads(line) for line in text.splitlines()]
    assert len(rows) == len(result.chunks)
    first = rows[0]
    assert set(first) == {
        "source_uri", "content_sha256", "media_type", "title",
        "chunk_index", "content", "section", "details", "char_len", "token_estimate",
    }
    assert first["details"]["chunk_profile"] == "book"


def test_normalize_epub_makes_mimetype_first_and_stored():
    """A non-conformant EPUB (mimetype compressed / not first) is repackaged so
    filetype can detect it — the fix for Docling's 'format None' on EPUB streams."""
    import io
    import zipfile

    import filetype

    from distiller.converter import _normalize_epub

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("META-INF/container.xml", "<container/>")
        z.writestr("OEBPS/c1.xhtml", "<html><body><p>hi</p></body></html>")
        # mimetype present but compressed and last: filetype sees a generic zip
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_DEFLATED)
    bad = buf.getvalue()
    assert filetype.guess_mime(bad) == "application/zip"

    fixed = _normalize_epub(bad)
    assert filetype.guess_mime(fixed) == "application/epub+zip"
    with zipfile.ZipFile(io.BytesIO(fixed)) as z:
        first = z.infolist()[0]
        assert first.filename == "mimetype"
        assert first.compress_type == zipfile.ZIP_STORED


def test_normalize_epub_passes_through_non_epub():
    from distiller.converter import _normalize_epub

    assert _normalize_epub(b"not a zip at all") == b"not a zip at all"


def test_write_outputs(settings, tmp_path):
    result = pipeline.process_document("handbook.pdf", b"x", settings)
    written = exporter.write_outputs(result, tmp_path)
    assert written["markdown"].read_text(encoding="utf-8") == SAMPLE_MD
    assert written["chunks"].exists()
    assert written["chunks"].read_text(encoding="utf-8").strip()
