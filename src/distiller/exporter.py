"""Serialize a DocumentResult to Markdown and JSONL, and write them to disk.

The JSONL is one chunk record per line — the shape a later PG Vector loader
INSERTs (add an ``embedding`` column in phase 2). Kept as pure string builders so
the Streamlit app can offer them as downloads without touching the filesystem.
"""

from __future__ import annotations

import json
from pathlib import Path

from .pipeline import DocumentResult


def chunks_jsonl(result: DocumentResult) -> str:
    """The document's chunks as newline-delimited JSON (trailing newline)."""
    lines = [json.dumps(record.to_dict(), ensure_ascii=False) for record in result.chunks]
    return "\n".join(lines) + ("\n" if lines else "")


def stem(result: DocumentResult) -> str:
    """Safe base filename derived from the source (no extension, no separators)."""
    return Path(result.source_uri).stem.replace("/", "_") or "document"


def write_outputs(result: DocumentResult, output_dir: str | Path) -> dict[str, Path]:
    """Write ``<stem>.md`` and ``<stem>.chunks.jsonl`` under ``output_dir``.

    Returns the paths written, keyed ``markdown`` and ``chunks``.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    base = stem(result)

    md_path = out / f"{base}.md"
    jsonl_path = out / f"{base}.chunks.jsonl"
    md_path.write_text(result.markdown, encoding="utf-8")
    jsonl_path.write_text(chunks_jsonl(result), encoding="utf-8")
    return {"markdown": md_path, "chunks": jsonl_path}
