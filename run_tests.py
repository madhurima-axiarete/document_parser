"""
run_tests.py

Runs all four extractors (pdfminer, landing_ai, claude, databricks) against the test
documents and writes Markdown output to output/{method}/ folders.

Usage:
    python run_tests.py

Output:
    output/pdfminer/LabReport.md
    output/landing_ai/LabReport.md
    output/claude/LabReport.md
    output/databricks/LabReport.md
    ... (one file per document per method)
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

# ── Load .env early so all extractors pick it up ──────────────────────────────

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import pdfminer_extractor
import landing_ai_extractor
import claude_extractor
import databricks_extractor

# ── Config ─────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent

TEST_FILES = [
    BASE_DIR / "PerformanceCharts.pdf",
    BASE_DIR / "LabReport.pdf",
    BASE_DIR / "Invoice.jpg",
    BASE_DIR / "AccidentStatement.pdf",
]

EXTRACTORS = [
    ("pdfminer",    pdfminer_extractor.extract),
    ("landing_ai",  landing_ai_extractor.extract),
    ("claude",      claude_extractor.extract),
    ("databricks",  databricks_extractor.extract),
]

OUTPUT_DIR = BASE_DIR / "output"


# ── Helpers ────────────────────────────────────────────────────────────────────



def _plain_summary(result: dict) -> str:
    """Plain text version of summary (no rich markup)."""
    raw_md = result.get("raw_markdown") or ""
    has_content = bool(raw_md.strip() or result.get("key_value_pairs") or result.get("sections"))

    if not has_content:
        first_warn = (result.get("warnings") or ["empty"])[0]
        return "✗ " + first_warn[:60]

    parts = []
    if result.get("raw_text_chars", 0):
        parts.append(f"{result['raw_text_chars']:,} chars")
    if raw_md:
        n_lines = len([l for l in raw_md.splitlines() if l.strip()])
        parts.append(f"{n_lines} lines")
    if result.get("key_value_pairs"):
        parts.append(f"{len(result['key_value_pairs'])} KVPs")
    if result.get("sections"):
        parts.append(f"{len(result['sections'])} sections")
    if result.get("tables"):
        parts.append(f"{len(result['tables'])} tables")

    return "✓ " + ", ".join(parts) if parts else "✗ empty"


# ── Markdown renderer ─────────────────────────────────────────────────────────


def _md_table(headers: list, rows: list) -> str:
    if not headers and not rows:
        return ""
    cols = headers or ([f"Col {i+1}" for i in range(len(rows[0]))] if rows else [])
    # Ensure every row has the same number of columns as headers
    def _pad(row: list) -> list:
        r = [str(c) for c in row]
        return r + [""] * max(0, len(cols) - len(r))
    lines = ["| " + " | ".join(str(h) for h in cols) + " |"]
    lines.append("| " + " | ".join("---" for _ in cols) + " |")
    for row in rows[:30]:
        lines.append("| " + " | ".join(_pad(row)) + " |")
    if len(rows) > 30:
        lines.append(f"_... {len(rows) - 30} more rows_")
    return "\n".join(lines)


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

    # Claude + Landing AI: raw_markdown is already in document order
    raw_md = (result.get("raw_markdown") or "").strip()
    if raw_md:
        lines.append(raw_md)
        lines.append("")

    # pdfminer: render sections and KVPs
    else:
        kvps = result.get("key_value_pairs") or []
        if kvps:
            lines.append("| Key | Value |")
            lines.append("| --- | --- |")
            for kv in kvps:
                key = str(kv.get("key", "")).replace("|", "\\|")
                val = str(kv.get("value", "")).replace("|", "\\|")
                lines.append(f"| {key} | {val} |")
            lines.append("")

        for i, tbl in enumerate(result.get("tables") or []):
            lines.append(f"### {tbl.get('source') or f'Table {i+1}'}")
            md = _md_table(tbl.get("headers", []), tbl.get("rows", []))
            if md:
                lines.append(md)
            lines.append("")

        for sec in (result.get("sections") or []):
            heading = "#" * min(sec.get("level", 1) + 2, 6)
            lines.append(f"{heading} {sec.get('title', '')}")
            if sec.get("content"):
                lines.append(sec["content"].strip())
            lines.append("")

    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────────────────────────


def run() -> None:
    # Create output directories
    for method_name, _ in EXTRACTORS:
        (OUTPUT_DIR / method_name).mkdir(parents=True, exist_ok=True)

    # results[file_name][method] = summary_str
    results: dict[str, dict[str, str]] = {}

    for test_file in TEST_FILES:
        if not test_file.exists():
            print(f"  [SKIP] {test_file.name} — file not found")
            continue

        results[test_file.name] = {}

        for method_name, extractor_fn in EXTRACTORS:
            print(f"  Running {method_name} on {test_file.name}...", end=" ", flush=True)
            try:
                result = extractor_fn(str(test_file))
            except Exception as exc:
                result = {
                    "file": test_file.name,
                    "method": method_name,
                    "raw_text_chars": 0,
                    "sections": [],
                    "tables": [],
                    "key_value_pairs": [],
                    "warnings": [f"Uncaught error: {exc}", traceback.format_exc()],
                }

            # Write Markdown output
            out_path = OUTPUT_DIR / method_name / (test_file.stem + ".md")
            out_path.write_text(_to_markdown(result), encoding="utf-8")

            summary = _plain_summary(result)
            results[test_file.name][method_name] = summary
            print(summary)

    # Print summary table
    _print_table(results)


def _print_table(results: dict[str, dict[str, str]]) -> None:
    try:
        from rich.table import Table
        from rich.console import Console
        console = Console()
        table = Table(title="Extraction Results", show_lines=True)
        table.add_column("File", style="bold")
        for method_name, _ in EXTRACTORS:
            table.add_column(method_name)
        for file_name, method_results in results.items():
            row = [file_name] + [method_results.get(m, "—") for m, _ in EXTRACTORS]
            table.add_row(*row)
        console.print(table)
    except ImportError:
        # Fallback plain table
        methods = [m for m, _ in EXTRACTORS]
        col_w = 28
        header = f"{'File':<30}" + "".join(f"{m:<{col_w}}" for m in methods)
        print("\n" + header)
        print("-" * (30 + col_w * len(methods)))
        for file_name, method_results in results.items():
            row = f"{file_name:<30}" + "".join(
                f"{method_results.get(m, '—'):<{col_w}}" for m in methods
            )
            print(row)

    print(f"\nOutputs written to: {OUTPUT_DIR}/")


if __name__ == "__main__":
    run()
