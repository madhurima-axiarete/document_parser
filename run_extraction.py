#!/usr/bin/env python3
"""
run_extraction.py

Unified document extraction runner with flexible method and file selection.

Usage:
    python run_extraction.py                    # Interactive mode
    python run_extraction.py --list             # Show available extractors
    python run_extraction.py --method claude    # Run only Claude
    python run_extraction.py --method gemma4,claude  # Run multiple
    python run_extraction.py --exclude-salesforce    # Skip Salesforce
    python run_extraction.py --method gemma4 --exclude-salesforce
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Import all extractors ──────────────────────────────────────────────────────

AVAILABLE_EXTRACTORS = {}

def _try_import(name: str, module_name: str) -> bool:
    """Try to import an extractor module."""
    try:
        module = __import__(module_name)
        AVAILABLE_EXTRACTORS[name] = {
            "module": module,
            "extract": module.extract,
        }
        return True
    except ImportError as e:
        AVAILABLE_EXTRACTORS[name] = {"error": str(e)}
        return False

_try_import("landing_ai", "landing_ai_extractor")
_try_import("claude", "claude_extractor")
_try_import("databricks", "databricks_extractor")
_try_import("llamaparse", "llamaparse_extractor")
_try_import("pdfminer", "pdfminer_extractor")
_try_import("gemma4", "gemma4_extractor")

# ── Config ─────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"

TEST_FILES = {
    "PerformanceCharts.pdf": BASE_DIR / "test_docs" / "PerformanceCharts.pdf",
    "LabReport.pdf": BASE_DIR / "test_docs" / "LabReport.pdf",
    "Invoice.jpg": BASE_DIR / "test_docs" / "Invoice.jpg",
    "AccidentStatement.pdf": BASE_DIR / "test_docs" / "AccidentStatement.pdf",
    "Salesforce (large)": BASE_DIR / "test_docs" / "salesforce_release_notes_3-25-2026.pdf",
}


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


def _to_markdown(result: dict) -> str:
    lines: list[str] = []
    method = result.get("method", "unknown")
    file_name = result.get("file", "")

    lines.append(f"# {file_name}")
    lines.append(f"**Method:** {method}")
    if result.get("raw_text_chars"):
        lines.append(f"**Characters extracted:** {result['raw_text_chars']:,}")
    lines.append("")

    if result.get("warnings"):
        lines.append("## ⚠ Warnings")
        for w in result["warnings"]:
            lines.append(f"- {w}")
        lines.append("")

    raw_md = (result.get("raw_markdown") or "").strip()
    if raw_md:
        lines.append(raw_md)
        lines.append("")
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

        for sec in (result.get("sections") or []):
            heading = "#" * min(sec.get("level", 1) + 2, 6)
            lines.append(f"{heading} {sec.get('title', '')}")
            if sec.get("content"):
                lines.append(sec["content"].strip())
            lines.append("")

    return "\n".join(lines)


def _print_extractor_status() -> None:
    """Print status of all available extractors."""
    print("\n📦 Available Extractors:\n")
    for name in sorted(AVAILABLE_EXTRACTORS.keys()):
        info = AVAILABLE_EXTRACTORS[name]
        if "error" in info:
            print(f"  ✗ {name:15s} — not available ({info['error'][:40]}...)")
        else:
            print(f"  ✓ {name:15s} — ready")
    print()


def _print_file_status() -> None:
    """Print status of all test files."""
    print("📄 Available Test Files:\n")
    for label, path in TEST_FILES.items():
        status = "✓" if path.exists() else "✗"
        print(f"  {status} {label:25s} ({path.name})")
    print()


# ── Main ───────────────────────────────────────────────────────────────────────

def run(methods: list[str], files: list[str], verbose: bool = False) -> None:
    """Run extraction with specified methods and files."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Filter methods
    available_methods = [m for m in methods if m in AVAILABLE_EXTRACTORS]
    invalid_methods = [m for m in methods if m not in AVAILABLE_EXTRACTORS]

    if invalid_methods:
        print(f"⚠ Unknown extractors: {', '.join(invalid_methods)}\n")

    if not available_methods:
        print("❌ No valid extractors selected.\n")
        _print_extractor_status()
        return

    # Filter files
    test_files = [path for label, path in TEST_FILES.items() if label in files]
    missing_files = [label for label, path in TEST_FILES.items() if label in files and not path.exists()]

    if missing_files:
        print(f"⚠ Missing files: {', '.join(missing_files)}\n")

    if not test_files:
        print("❌ No valid test files selected.\n")
        _print_file_status()
        return

    # Run extractors
    results: dict[str, dict[str, str]] = {}
    print(f"🚀 Running {len(available_methods)} extractor(s) on {len(test_files)} file(s)...\n")

    for test_file in test_files:
        results[test_file.name] = {}

        for method_name in available_methods:
            extractor_fn = AVAILABLE_EXTRACTORS[method_name]["extract"]
            print(f"  {method_name:12s} × {test_file.name}...", end=" ", flush=True)

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
                    "warnings": [f"Uncaught error: {exc}"],
                }
                if verbose:
                    print(f"\n     {traceback.format_exc()}\n")

            # Write Markdown output
            out_path = OUTPUT_DIR / method_name / (test_file.stem + ".md")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(_to_markdown(result), encoding="utf-8")

            summary = _plain_summary(result)
            results[test_file.name][method_name] = summary
            print(summary)

    # Print summary table
    _print_summary_table(results, available_methods)
    print(f"\n✅ Outputs written to: {OUTPUT_DIR}/\n")


def _print_summary_table(results: dict[str, dict[str, str]], methods: list[str]) -> None:
    """Print summary table of results."""
    try:
        from rich.table import Table
        from rich.console import Console

        console = Console()
        table = Table(title="Extraction Results", show_lines=True)
        table.add_column("File", style="bold")
        for method in methods:
            table.add_column(method)
        for file_name, method_results in results.items():
            row = [file_name] + [method_results.get(m, "—") for m in methods]
            table.add_row(*row)
        console.print(table)
    except ImportError:
        # Fallback plain table
        col_w = 28
        header = f"{'File':<30}" + "".join(f"{m:<{col_w}}" for m in methods)
        print("\n" + header)
        print("-" * (30 + col_w * len(methods)))
        for file_name, method_results in results.items():
            row = f"{file_name:<30}" + "".join(
                f"{method_results.get(m, '—'):<{col_w}}" for m in methods
            )
            print(row)


def interactive_mode() -> None:
    """Interactive mode to select extractors and files."""
    print("\n🎯 Document Extraction Runner (Interactive Mode)\n")

    # Show available options
    _print_extractor_status()
    _print_file_status()

    # Ask for methods
    print("Which extractors would you like to run? (comma-separated, or 'all')")
    methods_input = input(">>> ").strip()

    if methods_input.lower() == "all":
        methods = list(AVAILABLE_EXTRACTORS.keys())
    else:
        methods = [m.strip() for m in methods_input.split(",") if m.strip()]

    if not methods:
        print("❌ No extractors selected.\n")
        return

    # Ask for files
    print("\nWhich test files would you like to process? (comma-separated, or 'all')")
    print("Options: " + ", ".join(f"'{label}'" for label in TEST_FILES.keys()))
    files_input = input(">>> ").strip()

    if files_input.lower() == "all":
        files = list(TEST_FILES.keys())
    else:
        files = [f.strip() for f in files_input.split(",") if f.strip()]

    if not files:
        print("❌ No files selected.\n")
        return

    run(methods, files)


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Unified document extraction runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_extraction.py --list
  python run_extraction.py --method claude
  python run_extraction.py --method gemma4,claude --exclude-salesforce
  python run_extraction.py --method landing_ai --files "LabReport.pdf,Invoice.jpg"
        """,
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="List available extractors and test files",
    )

    parser.add_argument(
        "--method",
        type=str,
        help="Comma-separated list of extractors to run (or 'all')",
    )

    parser.add_argument(
        "--files",
        type=str,
        help="Comma-separated list of test files to process (or 'all')",
    )

    parser.add_argument(
        "--exclude-salesforce",
        action="store_true",
        help="Exclude the large Salesforce PDF from the run",
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print full error tracebacks",
    )

    args = parser.parse_args()

    # Handle --list
    if args.list:
        _print_extractor_status()
        _print_file_status()
        return

    # Determine methods
    if args.method:
        if args.method.lower() == "all":
            methods = list(AVAILABLE_EXTRACTORS.keys())
        else:
            methods = [m.strip() for m in args.method.split(",")]
    else:
        methods = None

    # Determine files
    if args.files:
        if args.files.lower() == "all":
            files = list(TEST_FILES.keys())
        else:
            files = [f.strip() for f in args.files.split(",")]
    else:
        files = None

    # Apply exclusions
    if args.exclude_salesforce:
        if files is None:
            files = list(TEST_FILES.keys())
        files = [f for f in files if f != "Salesforce (large)"]

    # If no args, use interactive mode
    if methods is None and files is None and not args.exclude_salesforce:
        interactive_mode()
        return

    # Default to all if not specified
    if methods is None:
        methods = list(AVAILABLE_EXTRACTORS.keys())
    if files is None:
        files = list(TEST_FILES.keys())

    # Exclude salesforce if flag set
    if args.exclude_salesforce and "Salesforce (large)" in files:
        files = [f for f in files if f != "Salesforce (large)"]

    run(methods, files, verbose=args.verbose)


if __name__ == "__main__":
    main()
