"""Command-line entry point: convert files to Markdown + chunks.jsonl.

    distiller path/to/file.pdf another.epub [--profile book|curated|generic]
                                            [--out DIR]

For batch/headless conversions; the Streamlit app (``app.py``) is the interactive
front end.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import ChunkProfile, get_settings
from .converter import ConverterError
from .exporter import write_outputs
from .pipeline import process_document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="distiller", description=__doc__)
    parser.add_argument("files", nargs="+", type=Path, help="Documents to convert.")
    parser.add_argument(
        "--profile",
        choices=[p.value for p in ChunkProfile],
        help="Chunk profile (default: DEFAULT_CHUNK_PROFILE from settings).",
    )
    parser.add_argument("--out", type=Path, help="Output directory (default: OUTPUT_DIR).")
    args = parser.parse_args(argv)

    settings = get_settings()
    profile = ChunkProfile(args.profile) if args.profile else None
    out_dir = args.out or settings.output_dir

    failures = 0
    for path in args.files:
        if not path.is_file():
            print(f"❌ Not a file: {path}", file=sys.stderr)
            failures += 1
            continue
        try:
            result = process_document(path.name, path.read_bytes(), settings, profile=profile)
        except ConverterError as exc:
            print(f"❌ {path.name}: {exc}", file=sys.stderr)
            failures += 1
            continue
        written = write_outputs(result, out_dir)
        note = f" ({len(result.filtered)} index chunk(s) filtered)" if result.filtered else ""
        print(
            f"✅ {path.name} → {len(result.chunks)} chunks{note}\n"
            f"   {written['markdown']}\n   {written['chunks']}"
        )

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
