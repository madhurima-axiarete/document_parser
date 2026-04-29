"""
run_llamaparse_salesforce.py

Runs LlamaParse extractor on the Salesforce PDF with automatic partitioning support.
"""

from __future__ import annotations

import traceback
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import llamaparse_extractor

# ── Config ─────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
SALESFORCE_PDF = BASE_DIR / "test_docs" / "salesforce_release_notes_3-25-2026.pdf"
OUTPUT_DIR = BASE_DIR / "output" / "llamaparse"


# ── Markdown renderer ──────────────────────────────────────────────────────────


def _to_markdown(result: dict) -> str:
    lines: list[str] = []
    method = result.get("method", "unknown")
    file_name = result.get("file", "")

    lines.append(f"# {file_name}")
    lines.append(f"**Method:** {method}")
    if result.get("raw_text_chars"):
        lines.append(f"**Characters extracted:** {result['raw_text_chars']:,}")
    lines.append("")

    # Warnings
    if result.get("warnings"):
        lines.append("## ⚠ Warnings")
        for w in result["warnings"]:
            lines.append(f"- {w}")
        lines.append("")

    # Raw markdown
    raw_md = (result.get("raw_markdown") or "").strip()
    if raw_md:
        lines.append(raw_md)
        lines.append("")

    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────────────────────────


def run() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not SALESFORCE_PDF.exists():
        print(f"✗ File not found: {SALESFORCE_PDF}")
        return

    print(f"Running LlamaParse on {SALESFORCE_PDF.name}...")
    print(f"(This will automatically split into 1000-page chunks due to API limit)\n")

    try:
        result = llamaparse_extractor.extract(str(SALESFORCE_PDF))
    except Exception as exc:
        result = {
            "file": SALESFORCE_PDF.name,
            "method": "llamaparse",
            "raw_text_chars": 0,
            "raw_markdown": "",
            "warnings": [f"Uncaught error: {exc}", traceback.format_exc()],
        }

    # Write Markdown output
    out_path = OUTPUT_DIR / (SALESFORCE_PDF.stem + ".md")
    out_path.write_text(_to_markdown(result), encoding="utf-8")

    # Print status
    if result.get("warnings"):
        print("✗ Extraction failed:")
        for warn in result["warnings"]:
            print(f"  - {warn}")
    else:
        chars = result.get("raw_text_chars", 0)
        print(f"✓ Success!")
        print(f"  Characters extracted: {chars:,}")
        print(f"  Output file: {out_path}")


if __name__ == "__main__":
    run()
