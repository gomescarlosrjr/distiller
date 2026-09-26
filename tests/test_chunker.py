"""Tests for the vendored chunker (pure, no external deps)."""

from distiller import chunker


def test_extract_title():
    assert chunker.extract_title("# The Title\n\nbody") == "The Title"
    assert chunker.extract_title("no title here") is None


def test_chunk_markdown_splits_on_headers():
    md = "## A\n\n" + ("alpha " * 50) + "\n\n## B\n\n" + ("beta " * 50)
    chunks = chunker.chunk_markdown(md, chunk_size=100, max_chunk_size=2000)
    headers = {c["metadata"]["header"] for c in chunks}
    assert "## A" in headers and "## B" in headers


def test_chunk_markdown_hard_cap_never_exceeded():
    # A single unbroken run far above the cap must still be split under it.
    md = "## H\n\n" + ("x" * 5000)
    chunks = chunker.chunk_markdown(md, chunk_size=1000, max_chunk_size=500)
    assert chunks
    assert all(len(c["content"]) <= 500 for c in chunks)


def test_chunk_markdown_preserves_all_content():
    md = "## H\n\n" + " ".join(f"word{i}" for i in range(400))
    chunks = chunker.chunk_markdown(md, chunk_size=200, overlap=0, max_chunk_size=2000)
    joined = " ".join(c["content"] for c in chunks)
    assert "word0" in joined and "word399" in joined


def test_is_index_like_detects_toc():
    toc = "\n".join(
        [
            "Introduction ......... 1",
            "Methods . . . . . . . 12",
            "Results ............ 34",
            "Aeroponics, 217",
            "Nutrients, 45, 88-91",
            "Conclusion ......... 99",
        ]
    )
    assert chunker.is_index_like(toc) is True


def test_is_index_like_rejects_prose():
    prose = (
        "Cannabis has been used for centuries. The endocannabinoid system, "
        "described in 1992, regulates many processes. Dosing at 2,5 mg is common "
        "in clinical practice. This paragraph is ordinary prose, not an index."
    )
    assert chunker.is_index_like(prose) is False


def test_chunk_book_keeps_table_whole():
    table = "| a | b |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |"
    md = f"# Doc\n\nSome intro paragraph.\n\n{table}\n\nA closing paragraph."
    chunks = chunker.chunk_book(md, max_chunk_size=2000)
    table_chunks = [c for c in chunks if "| a | b |" in c["content"]]
    assert len(table_chunks) == 1
    assert "| 1 | 2 |" in table_chunks[0]["content"]
    assert "| 3 | 4 |" in table_chunks[0]["content"]


def test_chunk_book_respects_cap():
    md = "## H\n\n" + ("palavra " * 2000)
    chunks = chunker.chunk_book(md, max_chunk_size=800)
    assert chunks
    assert all(len(c["content"]) <= 800 for c in chunks)


def test_chunk_curated_extracts_legal_refs():
    md = "## Capítulo V\n\n### Art. 37\n\nO servidor deve observar a legalidade."
    chunks = chunker.chunk_curated(md, max_chunk_size=2000)
    body = [c for c in chunks if "servidor" in c["content"]]
    assert body
    meta = body[0]["metadata"]
    assert meta.get("article") == "Art. 37"
    assert meta.get("chapter") == "Capítulo V"
