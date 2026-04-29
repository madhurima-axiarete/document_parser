#!/usr/bin/env python3
"""
liteparse_extractor.py

Parses documents using LiteParse (local, no LLM/cloud required).
Uses PDF.js for text extraction + Tesseract OCR for scanned/image files.

Install: pip install liteparse
Run:     python liteparse_extractor.py

Outputs plain text files to output/liteparse/<filename>.txt
"""

import json
import sys
import time
from pathlib import Path
from liteparse import LiteParse


def get_test_files(test_docs_dir: Path) -> list[Path]:
    """Auto-discover all supported document files in test_docs directory."""
    if not test_docs_dir.exists():
        print(f"❌ test_docs directory not found at {test_docs_dir}")
        sys.exit(1)

    supported_extensions = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".bmp"}
    files = [
        f
        for f in sorted(test_docs_dir.iterdir())
        if f.is_file() and f.suffix.lower() in supported_extensions
    ]

    return files


def detect_document_type(file_path: Path) -> tuple[str, int]:
    """
    Detect if document is high-res scan or born-digital, return type and adaptive DPI.
    High-res scans (width > 1500 or height > 2000) need lower DPI to avoid over-zoom.
    """
    try:
        import PyPDF2
        with open(file_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            page = reader.pages[0]
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)

        # High-res scan detected
        if width > 1500 or height > 2000:
            return "high-res-scan", 150
        else:
            return "born-digital", 300
    except Exception:
        # Fallback: assume born-digital if detection fails
        return "unknown", 300


def parse_file(parser: LiteParse, file_path: Path, output_dir: Path) -> dict:
    """Parse a single file and save output."""
    txt_path = output_dir / f"{file_path.stem}.txt"
    json_path = output_dir / f"{file_path.stem}.json"

    print(f"\nParsing: {file_path.name}")
    start_time = time.time()

    try:
        # Detect document type and use adaptive DPI
        doc_type, adaptive_dpi = detect_document_type(file_path)
        print(f"  Document type: {doc_type} (DPI: {adaptive_dpi})")

        # Use best parameters for accurate extraction (matching .js version)
        result = parser.parse(
            str(file_path),
            ocr_enabled=True,                  # Enable OCR for all documents
            precise_bounding_box=True,         # Get exact coordinates (layout-aware)
            preserve_very_small_text=True,     # Keep footnotes, captions, fine print
            dpi=adaptive_dpi,                  # Adaptive: 150 for scans, 300 for digital
            ocr_language="en",                 # English language for OCR
            num_workers=8,                     # Parallel OCR processing
        )
        elapsed = time.time() - start_time

        # Save plain text output
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(result.text or "")

        # Save structured JSON output (preserves coordinates, structure, everything)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result.json, f, indent=2)

        print(f"  ✓ Done in {elapsed:.2f}s")
        print(f"  ✓ Saved → {txt_path}")
        print(f"  ✓ Saved → {json_path}")

        return {"name": file_path.name, "elapsed": elapsed, "error": None}

    except Exception as e:
        elapsed = time.time() - start_time
        print(f"  ✗ ERROR: {str(e)}")
        return {"name": file_path.name, "elapsed": elapsed, "error": str(e)}


def main():
    """Main extraction pipeline."""
    # Setup paths
    project_root = Path(__file__).parent
    test_docs_dir = project_root / "test_docs"
    output_dir = project_root / "output" / "liteparse"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Discover files
    test_files = get_test_files(test_docs_dir)

    if not test_files:
        print(f"❌ No PDF/image files found in {test_docs_dir}")
        sys.exit(1)

    print(f"Found {len(test_files)} file(s) to process:\n")
    for f in test_files:
        print(f"  • {f.name}")
    print()

    # Create parser (options are passed to parse() method)
    parser = LiteParse()

    # Parse all files
    results = []
    for file_path in test_files:
        result = parse_file(parser, file_path, output_dir)
        results.append(result)

    # Print summary
    print("\n--- Summary ---")
    for r in results:
        if r["error"]:
            print(f"  {r['name']}: FAILED — {r['error']}")
        else:
            print(f"  {r['name']}: {r['elapsed']:.2f}s")


if __name__ == "__main__":
    main()
