"""
run_llamaparse.py

Runs LlamaParse extractor on test documents and writes Markdown output.
"""

from __future__ import annotations

import os
import traceback
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import llamaparse_extractor

# ── Config ─────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent

TEST_FILES = [
    BASE_DIR / "test_docs" / "PerformanceCharts.pdf",
    BASE_DIR / "test_docs" / "LabReport.pdf",
    BASE_DIR / "test_docs" / "Invoice.jpg",
    BASE_DIR / "test_docs" / "AccidentStatement.pdf",
    BASE_DIR / "test_docs" / "salesforce_release_notes_3-25-2026.pdf",
]

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

    for test_file in TEST_FILES:
        if not test_file.exists():
            print(f"  [SKIP] {test_file.name} — file not found")
            continue

        print(f"  Running LlamaParse on {test_file.name}...", end=" ", flush=True)
        try:
            result = llamaparse_extractor.extract(str(test_file))
        except Exception as exc:
            result = {
                "file": test_file.name,
                "method": "llamaparse",
                "raw_text_chars": 0,
                "raw_markdown": "",
                "warnings": [f"Uncaught error: {exc}", traceback.format_exc()],
            }

        # Write Markdown output
        out_path = OUTPUT_DIR / (test_file.stem + ".md")
        out_path.write_text(_to_markdown(result), encoding="utf-8")

        # Print status
        if result.get("warnings"):
            first_warn = result["warnings"][0][:60]
            print(f"✗ {first_warn}")
        else:
            chars = result.get("raw_text_chars", 0)
            print(f"✓ {chars:,} chars")

    print(f"\nOutputs written to: {OUTPUT_DIR}/")


if __name__ == "__main__":
    run()
