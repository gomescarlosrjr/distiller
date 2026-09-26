"""distiller — Streamlit UI.

Run:  uv run streamlit run app.py

Upload documents (PDF, EPUB, DOCX, PPTX, XLSX, HTML, images, …), convert to
Markdown via Docling, split into retrieval-ready chunks, and download the
Markdown + a chunks.jsonl ready for a future PG Vector load.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from distiller.config import ChunkProfile, ExtractionEngine, VlmProvider, get_settings
from distiller.converter import ConverterError
from distiller.exporter import chunks_jsonl, stem, write_outputs
from distiller.pipeline import process_document

st.set_page_config(page_title="distiller", page_icon="📄", layout="wide")

UPLOAD_TYPES = [
    "pdf", "epub", "docx", "doc", "pptx", "xlsx",
    "html", "htm", "xhtml", "md", "txt", "csv", "adoc",
    "png", "jpg", "jpeg", "tiff", "bmp", "webp",
]

base = get_settings()

st.title("📄 distiller")
st.caption("Documents → Markdown → retrieval-ready chunks (Docling). PG-Vector-ready export.")

# --- Sidebar: run configuration ---------------------------------------------
with st.sidebar:
    st.header("Settings")

    engine = st.radio(
        "Extraction engine",
        options=list(ExtractionEngine),
        format_func=lambda e: {"local": "Local (offline)", "vlm": "VLM (best quality)"}[e.value],
        index=list(ExtractionEngine).index(base.extraction_engine),
        help="Local runs Docling in-process. VLM routes hard/scanned page images "
        "through a remote vision model (born-digital DOCX/EPUB/HTML always use the "
        "local structured backend).",
    )

    do_ocr = st.toggle(
        "OCR (scanned PDFs/images)", value=base.do_ocr,
        help="Local engine only. Slower; needed for scanned/photographed pages.",
    )

    provider = base.vlm_provider
    if engine is ExtractionEngine.VLM:
        provider = st.selectbox(
            "VLM provider",
            options=list(VlmProvider),
            format_func=lambda p: p.value,
            index=list(VlmProvider).index(base.vlm_provider),
        )
        key_set = bool(
            base.groq_api_key if provider is VlmProvider.GROQ else base.anthropic_api_key
        )
        (st.success if key_set else st.warning)(
            f"{provider.value} API key: {'set' if key_set else 'missing — set it in .env'}"
        )

    st.divider()
    profile = st.selectbox(
        "Chunk profile",
        options=list(ChunkProfile),
        format_func=lambda p: p.value,
        index=list(ChunkProfile).index(base.default_chunk_profile),
        help="book = whole documents (overlap, tables kept whole); "
        "curated = structured markdown; generic = header/paragraph aware.",
    )
    max_chunk_chars = st.number_input(
        "Max chunk chars", min_value=200, max_value=20000,
        value=base.max_chunk_chars, step=100,
    )
    filter_index = st.toggle(
        "Filter index/TOC chunks", value=base.filter_index_chunks,
        help="Index/TOC-style chunks are excluded from the export (always reported below).",
    )
    save_to_disk = st.toggle(
        f"Also save to {base.output_dir}", value=False,
    )

settings = base.model_copy(
    update={
        "extraction_engine": engine,
        "do_ocr": do_ocr,
        "vlm_provider": provider,
        "max_chunk_chars": int(max_chunk_chars),
        "filter_index_chunks": filter_index,
    }
)

# --- Main: upload + convert --------------------------------------------------
uploaded = st.file_uploader(
    "Upload documents", type=UPLOAD_TYPES, accept_multiple_files=True
)

if uploaded and st.button("Convert", type="primary"):
    for file in uploaded:
        with st.expander(f"📄 {file.name}", expanded=len(uploaded) == 1):
            with st.spinner(f"Converting {file.name}…"):
                try:
                    result = process_document(
                        file.name, file.getvalue(), settings, profile=profile
                    )
                except ConverterError as exc:
                    st.error(str(exc))
                    continue
                except Exception as exc:  # unexpected — show it rather than a blank page
                    st.exception(exc)
                    continue

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Chunks", len(result.chunks))
            c2.metric("Filtered", len(result.filtered))
            c3.metric("Profile", result.profile)
            c4.metric("Characters", f"{len(result.markdown):,}")

            st.subheader(result.title)

            if result.filtered:
                st.warning(f"{len(result.filtered)} index/TOC-style chunk(s) filtered out:")
                for fc in result.filtered:
                    st.text(f"• [{fc.section or '—'}] {fc.preview!r}")

            tab_md, tab_chunks = st.tabs(["Markdown", "Chunks"])
            with tab_md:
                st.markdown(
                    result.markdown[:20000]
                    + ("\n\n…(truncated preview)…" if len(result.markdown) > 20000 else "")
                )
            with tab_chunks:
                if result.chunks:
                    df = pd.DataFrame(
                        {
                            "idx": [c.chunk_index for c in result.chunks],
                            "section": [c.section or "" for c in result.chunks],
                            "chars": [c.char_len for c in result.chunks],
                            "~tokens": [c.token_estimate for c in result.chunks],
                            "preview": [c.content[:160] for c in result.chunks],
                        }
                    )
                    st.dataframe(df, use_container_width=True, hide_index=True)
                else:
                    st.info("No chunks produced.")

            base_name = stem(result)
            d1, d2 = st.columns(2)
            d1.download_button(
                "⬇️ Markdown (.md)",
                data=result.markdown.encode("utf-8"),
                file_name=f"{base_name}.md",
                mime="text/markdown",
            )
            d2.download_button(
                "⬇️ Chunks (.jsonl)",
                data=chunks_jsonl(result).encode("utf-8"),
                file_name=f"{base_name}.chunks.jsonl",
                mime="application/x-ndjson",
            )

            if save_to_disk:
                written = write_outputs(result, base.output_dir)
                st.success(f"Saved: {written['markdown']}  •  {written['chunks']}")
