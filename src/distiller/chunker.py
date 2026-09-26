"""Text chunking utilities for document ingestion.

Vendored and adapted from terpafy-ai/courier (src/common/text_chunker.py) — the
logic is proven in production and dependency-free (pure ``re``), so it is copied
here rather than reimplemented.

Three entry points, all returning ``[{"content": str, "metadata": dict}]``:

- :func:`chunk_markdown` — the generic header-aware splitter (``generic`` profile).
- :func:`chunk_curated` — the ``curated`` profile for hand-written, structured
  markdown (headers are the document's own structure); no overlap.
- :func:`chunk_book` — the ``book`` profile for whole documents (e.g. PDFs
  converted by Docling), with paragraph overlap and tables kept whole.

Sizes are in characters; token targets are converted with ``CHARS_PER_TOKEN``
rather than pulling in a tokenizer dependency.
"""

import re
from typing import Any, NamedTuple

# Rough characters-per-token ratio for English/Portuguese prose. A constant
# instead of a tokenizer dependency: the profiles only need a target, and the
# hard cap (max_chunk_size) already guards the embedding context window.
CHARS_PER_TOKEN = 4

# ``curated`` profile: header-aware split, no overlap.
CURATED_TARGET_TOKENS = 600
# ``book`` profile: recursive paragraph split with overlap, tables kept whole.
BOOK_TARGET_TOKENS = 400
BOOK_OVERLAP_TOKENS = 80


def chunk_markdown(
    content: str,
    chunk_size: int = 1000,
    overlap: int = 200,
    min_chunk_size: int = 100,
    max_chunk_size: int | None = None,
) -> list[dict[str, Any]]:
    """
    Split markdown content into chunks based on headers and paragraphs.

    Strategy:
    1. Split by markdown headers (##, ###, etc.)
    2. Within sections, split by paragraphs if needed
    3. Maintain overlap between chunks for context
    4. Preserve markdown structure in metadata
    5. Hard-split any chunk above max_chunk_size at word boundaries, so no
       emitted chunk can exceed the embedding model's context window

    This function never drops content. Index/TOC filtering (is_index_like) is
    the caller's decision, so any discarded chunk stays observable in the
    caller's output instead of vanishing here.

    Args:
        content: Markdown text to chunk
        chunk_size: Target size for each chunk (characters)
        overlap: Number of characters to overlap between chunks
        min_chunk_size: Minimum size for a chunk to be included
        max_chunk_size: Hard upper bound on emitted chunk length (characters).
                        None disables the cap. chunk_size is only a target —
                        sections without paragraph breaks (long unbroken text,
                        tables) can exceed it, so callers embedding the chunks
                        should always pass their model's safe limit.

    Returns:
        List of dicts with 'content' and 'metadata' keys. Metadata carries
        'header' (the section's own ## / ### header) and 'parent_header' (the
        enclosing ## header of a ### section; empty otherwise).
    """
    chunks = []

    # Split by markdown headers (## or ###)
    header_pattern = r"(^#{2,3}\s+.+$)"
    sections = re.split(header_pattern, content, flags=re.MULTILINE)

    # Reconstruct sections with their headers
    current_header = ""
    last_h2 = ""  # most recent ## header seen
    current_parent = ""  # the ## header enclosing a ### section
    current_section = ""

    for _i, section in enumerate(sections):
        # Check if this is a header
        if re.match(r"^#{2,3}\s+", section):
            # Process previous section if exists
            if current_section.strip():
                section_chunks = _chunk_section(
                    current_section.strip(),
                    current_header,
                    current_parent,
                    chunk_size,
                    overlap,
                    min_chunk_size,
                )
                chunks.extend(section_chunks)

            # Start new section
            current_header = section.strip()
            if re.match(r"^##\s", current_header):
                last_h2, current_parent = current_header, ""
            else:
                current_parent = last_h2
            current_section = section + "\n"
        else:
            current_section += section

    # Process final section
    if current_section.strip():
        section_chunks = _chunk_section(
            current_section.strip(),
            current_header,
            current_parent,
            chunk_size,
            overlap,
            min_chunk_size,
        )
        chunks.extend(section_chunks)

    if max_chunk_size is not None:
        capped: list[dict[str, Any]] = []
        for chunk in chunks:
            if len(chunk["content"]) <= max_chunk_size:
                capped.append(chunk)
            else:
                for piece in _hard_split(chunk["content"], max_chunk_size, overlap):
                    capped.append({"content": piece, "metadata": dict(chunk["metadata"])})
        chunks = capped

    return chunks


def _hard_split(text: str, max_size: int, overlap: int) -> list[str]:
    """
    Split text into pieces of at most max_size characters.

    Pieces break at the last whitespace before the limit so words stay intact,
    and each piece re-starts `overlap` characters before the previous cut so
    context carries over (mirroring the paragraph-level overlap behaviour).
    A run with no whitespace at all falls back to a mid-word cut — dropping
    content is never an option here.
    """
    # Cap the overlap so every iteration makes progress even after backing up.
    overlap = min(overlap, max_size // 2)

    pieces: list[str] = []
    start = 0
    while start < len(text):
        remaining = text[start:]
        if len(remaining) <= max_size:
            piece = remaining.strip()
            if piece:
                pieces.append(piece)
            break

        window = remaining[:max_size]
        cut = max(window.rfind(" "), window.rfind("\n"), window.rfind("\t"))
        found_boundary = cut > overlap
        if not found_boundary:
            # No usable word boundary (unbroken run) — cut mid-word.
            cut = max_size

        piece = window[:cut].strip()
        if piece:
            pieces.append(piece)

        next_start = start + max(cut - overlap, 1)
        if found_boundary:
            # Align the overlap re-start to a word boundary so no piece begins
            # mid-word. The scan is bounded: the cut itself sits on whitespace,
            # so it stops there at the latest — nothing is skipped.
            while not text[next_start - 1].isspace():
                next_start += 1
        start = next_start

    return pieces


# --- Index/TOC page detection ----------------------------------------------
#
# Book index and table-of-contents pages survive PDF→Markdown conversion as
# ordinary text and would otherwise be embedded as chunks; they score well on
# keyword overlap while carrying no answerable content. The heuristic below
# detects them by line shape. It is deliberately conservative: a false negative
# just leaves one junk chunk, while a false positive drops real prose — so a
# chunk is only flagged when *most* of its lines look like index entries and
# there are enough of them to rule out coincidence. This function only
# *classifies*; the caller decides to drop and reports every filtered chunk, so
# a false positive is always visible in the output.

# "Getting Started ......... 12"  /  "Intro . . . . 7" — dot leader + page.
_DOT_LEADER_LINE = re.compile(r"\.(\s*\.){2,}\s*\d{1,4}\s*$")

# "Aeroponics, 217"  /  "Nutrients, 45, 88-91" — a short entry ending in one
# or more comma-separated page references. The prefix excludes sentence
# punctuation and is length-bounded, so wrapped prose that happens to end in a
# number does not match. Whitespace after each comma is mandatory: pt-BR
# decimal commas ("a EC ideal fica em 1,2") must never look like a page ref.
_PAGE_REF_LINE = re.compile(r"^[^.!?|]{1,45}?(,\s+\d{1,4}(\s*[-–]\s*\d{1,4})?)+\s*$")

_INDEX_MIN_LINES = 5
_INDEX_LINE_RATIO = 0.6


def _is_index_line(line: str) -> bool:
    """True when a single line is shaped like an index/TOC entry."""
    if "|" in line:  # markdown table row, never an index entry
        return False
    return bool(_DOT_LEADER_LINE.search(line) or _PAGE_REF_LINE.match(line))


def is_index_like(content: str) -> bool:
    """
    Heuristically detect book index / table-of-contents style chunks.

    A chunk qualifies only when at least _INDEX_MIN_LINES of its non-blank
    lines are index-shaped AND those lines make up at least _INDEX_LINE_RATIO
    of the chunk — real prose never looks like that, so false positives are
    biased against at the cost of letting sparse index fragments through.
    """
    lines = [line.strip() for line in content.splitlines()]
    lines = [line for line in lines if line]
    if len(lines) < _INDEX_MIN_LINES:
        return False

    hits = sum(1 for line in lines if _is_index_line(line))
    return hits >= _INDEX_MIN_LINES and hits / len(lines) >= _INDEX_LINE_RATIO


def _chunk_section(
    section: str,
    header: str,
    parent_header: str,
    chunk_size: int,
    overlap: int,
    min_chunk_size: int,
) -> list[dict[str, Any]]:
    """
    Chunk a single section by paragraphs if needed.

    Args:
        section: Section content to chunk
        header: Section header for metadata
        parent_header: Enclosing ## header of a ### section (empty otherwise)
        chunk_size: Target chunk size
        overlap: Overlap between chunks
        min_chunk_size: Minimum chunk size

    Returns:
        List of chunk dicts
    """
    metadata = {"header": header, "parent_header": parent_header}

    # If section fits in one chunk, return it
    if len(section) <= chunk_size:
        return [{"content": section, "metadata": dict(metadata)}]

    # Split by paragraphs (double newline)
    paragraphs = re.split(r"\n\s*\n", section)

    chunks = []
    current_chunk = ""
    previous_chunk = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # If adding this paragraph would exceed chunk_size
        if current_chunk and len(current_chunk) + len(para) + 2 > chunk_size:
            # Save current chunk
            if len(current_chunk) >= min_chunk_size:
                chunks.append(
                    {
                        "content": current_chunk.strip(),
                        "metadata": dict(metadata),
                    }
                )
                previous_chunk = current_chunk

            # Start new chunk with overlap from previous
            if previous_chunk and overlap > 0:
                # Take last overlap characters from previous chunk
                overlap_text = previous_chunk[-overlap:]
                current_chunk = overlap_text + "\n\n" + para
            else:
                current_chunk = para
        else:
            # Add paragraph to current chunk
            if current_chunk:
                current_chunk += "\n\n" + para
            else:
                current_chunk = para

    # Add final chunk
    if current_chunk and len(current_chunk) >= min_chunk_size:
        chunks.append(
            {
                "content": current_chunk.strip(),
                "metadata": dict(metadata),
            }
        )

    return chunks


def extract_title(content: str) -> str | None:
    """
    Extract title from markdown content (first # header).

    Args:
        content: Markdown content

    Returns:
        Title string or None if not found
    """
    match = re.search(r"^#\s+(.+)$", content, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


# --- Manifest chunk profiles -------------------------------------------------

# Legal references named in a curated section header: "Art. 37", "Art. 1º",
# "Arts. 35–38", "Capítulo V". Recorded in a chunk's details so a compliance
# chunk can be cited by norm and article without re-parsing its text.
_ARTICLE_RE = re.compile(r"\bArts?\.\s*\d+[ºo°]?(?:\s*[–-]\s*\d+[ºo°]?)?")
_CHAPTER_RE = re.compile(r"\bCap[íi]tulo\s+(?:[IVXLC]+|\d+)\b")


def legal_refs(header: str, parent_header: str = "") -> dict[str, str]:
    """Article/chapter named by a section header (and its enclosing ## header).

    Returns only the keys found, so callers can merge the result straight into
    chunk details: ``{"article": "Arts. 35–38", "chapter": "Capítulo V"}``.
    """
    refs: dict[str, str] = {}
    article = _ARTICLE_RE.search(header)
    if article:
        refs["article"] = article.group(0)
    chapter = _CHAPTER_RE.search(parent_header) or _CHAPTER_RE.search(header)
    if chapter:
        refs["chapter"] = chapter.group(0)
    return refs


def chunk_curated(content: str, max_chunk_size: int) -> list[dict[str, Any]]:
    """
    ``curated`` profile: header-aware split, ~600-token target, no overlap.

    Meant for hand-written, structured markdown whose ## / ### headers are the
    document's own structure (chapter, article). Each chunk's metadata carries
    'header' (stored as the chunk's section) plus 'article' / 'chapter' when the
    headers name them (see :func:`legal_refs`). No text is dropped — a short
    final paragraph of a section is a chunk of its own — except a header line
    with no body, which its ### sections already carry as 'parent_header'.

    Args:
        content: Markdown text
        max_chunk_size: Hard cap in characters (the embedding model's safe
            limit); the target never exceeds it.
    """
    target = min(CURATED_TARGET_TOKENS * CHARS_PER_TOKEN, max_chunk_size)
    chunks = chunk_markdown(
        content, chunk_size=target, overlap=0, min_chunk_size=1, max_chunk_size=max_chunk_size
    )
    kept: list[dict[str, Any]] = []
    for chunk in chunks:
        metadata = chunk["metadata"]
        if chunk["content"] == metadata["header"]:
            continue
        metadata.update(legal_refs(metadata["header"], metadata["parent_header"]))
        kept.append(chunk)
    return kept


_ATX_HEADER_RE = re.compile(r"^#{1,6}\s+\S")
_TABLE_LINE_RE = re.compile(r"^\s*\|")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*\|")


class _Block(NamedTuple):
    """A run of prose or one pipe table, tagged with the nearest header above it."""

    text: str
    header: str
    is_table: bool


def _split_blocks(content: str) -> list[_Block]:
    """Split markdown into prose blocks and pipe-table blocks, in order.

    A block starts at every ATX header and at every table boundary, so each
    block knows the header in effect where it begins.
    """
    blocks: list[_Block] = []
    header = ""
    prose: list[str] = []
    table: list[str] = []

    def flush(lines: list[str], is_table: bool) -> None:
        text = "\n".join(lines).strip()
        if text:
            blocks.append(_Block(text, header, is_table))
        lines.clear()

    for line in content.splitlines():
        if _TABLE_LINE_RE.match(line):
            if not table:
                flush(prose, False)
            table.append(line)
            continue
        if table:
            flush(table, True)
        if _ATX_HEADER_RE.match(line):
            flush(prose, False)
            header = line.strip()
        prose.append(line)
    flush(table, True)
    flush(prose, False)
    return blocks


def _prose_units(text: str, max_size: int) -> list[str]:
    """Paragraphs of a prose block, each at most max_size characters.

    A paragraph longer than max_size is hard-split at word boundaries without
    overlap — the packer in chunk_book adds the overlap between chunks.
    """
    units: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_size:
            units.append(para)
        else:
            units.extend(_hard_split(para, max_size, 0))
    return units


def _overlap_tail(text: str, overlap: int) -> str:
    """Last `overlap` characters of `text`, moved forward to a word boundary."""
    if overlap <= 0:
        return ""
    if len(text) <= overlap:
        return text
    tail = text[-overlap:]
    if not text[-overlap - 1].isspace():
        # The cut landed mid-word: drop the partial first word.
        boundary = re.search(r"\s", tail)
        tail = tail[boundary.end() :] if boundary else ""
    return tail.strip()


def _split_table(table: str, max_size: int) -> list[str]:
    """A pipe table as one piece, or row groups of at most max_size characters.

    Only a table longer than max_size is split, and every group repeats the
    header and separator rows so each piece still reads as a table. A single
    row wider than max_size is hard-split on its own.
    """
    if len(table) <= max_size:
        return [table]

    lines = table.splitlines()
    head = lines[:2] if len(lines) > 2 and _TABLE_SEPARATOR_RE.match(lines[1]) else []
    head_text = "\n".join(head)
    if len(head_text) > max_size // 2:
        head, head_text = [], ""  # a header too wide to repeat is not repeated
    body = lines[len(head) :]

    pieces: list[str] = []
    rows: list[str] = []
    size = len(head_text)
    for row in body:
        if len(head_text) + 1 + len(row) > max_size:
            if rows:
                pieces.append("\n".join(head + rows))
                rows, size = [], len(head_text)
            pieces.extend(_hard_split(row, max_size, 0))
            continue
        if rows and size + 1 + len(row) > max_size:
            pieces.append("\n".join(head + rows))
            rows, size = [], len(head_text)
        rows.append(row)
        size += len(row) + 1
    if rows:
        pieces.append("\n".join(head + rows))
    return pieces


def chunk_book(content: str, max_chunk_size: int) -> list[dict[str, Any]]:
    """
    ``book`` profile: recursive paragraph split, ~400 tokens, ~80 overlap.

    Meant for whole documents converted by Docling, whose markdown carries pipe
    tables (dose tables, interaction tables) that must not be cut mid-table:
    a table is always a chunk of its own — larger than the target if need be,
    split by rows only above max_chunk_size (see :func:`_split_table`).
    Prose is packed by paragraph up to the target; each chunk after the first
    starts with the word-aligned tail of the previous one, so a fact that
    straddles a boundary is embedded whole at least once. Oversized paragraphs
    are split at word boundaries first. Chunk metadata carries 'header': the
    nearest ATX header above the chunk's first line.

    Args:
        content: Markdown text (Docling output)
        max_chunk_size: Hard cap in characters (the embedding model's safe
            limit); the target never exceeds it and no chunk does either.
    """
    target = min(BOOK_TARGET_TOKENS * CHARS_PER_TOKEN, max_chunk_size)
    overlap = min(BOOK_OVERLAP_TOKENS * CHARS_PER_TOKEN, target // 4)
    # The overlap tail is part of the chunk budget, so a unit must leave room
    # for it plus the "\n\n" joiner.
    unit_max = target - overlap - 2

    chunks: list[dict[str, Any]] = []
    parts: list[str] = []  # the chunk being built; parts[0] may be an overlap tail
    size = 0  # len("\n\n".join(parts))
    header = ""  # header of the chunk being built
    tail_header = ""  # header of the block the last appended unit came from
    fresh = True  # no unit appended yet (parts is empty or holds only the tail)

    def emit() -> str:
        text = "\n\n".join(parts)
        chunks.append({"content": text, "metadata": {"header": header}})
        return text

    for block in _split_blocks(content):
        if block.is_table:
            if parts:
                emit()
                parts, size, fresh = [], 0, True
            for piece in _split_table(block.text, max_chunk_size):
                chunks.append({"content": piece, "metadata": {"header": block.header}})
            continue

        for unit in _prose_units(block.text, unit_max):
            if parts and size + 2 + len(unit) > target:
                tail = _overlap_tail(emit(), overlap)
                parts = [tail] if tail else []
                size = len(tail)
                # A chunk that opens with the overlap tail takes the header of
                # the block the tail came from — the nearest header above its
                # first line. Only a chunk that opens with one of this block's
                # own units takes the block's header.
                if tail:
                    header, fresh = tail_header, False
                else:
                    fresh = True
            if fresh:
                header, fresh = block.header, False
            size += len(unit) + (2 if parts else 0)
            parts.append(unit)
            tail_header = block.header
    if parts:
        emit()
    return chunks
