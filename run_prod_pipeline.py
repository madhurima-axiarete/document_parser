#!/usr/bin/env python3
"""
run_prod_pipeline.py

CLI wrapper for production_pipeline with flexible file selection.

Usage:
    python3 run_prod_pipeline.py                    # All test_docs
    python3 run_prod_pipeline.py --exclude-salesforce  # Skip Salesforce
    python3 run_prod_pipeline.py -v                    # Verbose output
    python3 run_prod_pipeline.py --exclude-salesforce -v
    python3 run_prod_pipeline.py --help                # Show options
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from production_pipeline import run, costs

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output/production_pipeline"

TEST_FILES = {
    "PerformanceCharts.pdf": BASE_DIR / "test_docs" / "PerformanceCharts.pdf",
    "LabReport.pdf": BASE_DIR / "test_docs" / "LabReport.pdf",
    "Invoice.jpg": BASE_DIR / "test_docs" / "Invoice.jpg",
    "AccidentStatement.pdf": BASE_DIR / "test_docs" / "AccidentStatement.pdf",
    "01_image_across_page_boundary.pdf": BASE_DIR / "test_docs" / "01_image_across_page_boundary.pdf",
    "02_table_across_page_boundary.pdf": BASE_DIR / "test_docs" / "02_table_across_page_boundary.pdf",
    "03_image_across_chunk_boundary_same_page.pdf": BASE_DIR / "test_docs" / "03_image_across_chunk_boundary_same_page.pdf",
    "04_50_page_mixed_boundary_stress.pdf": BASE_DIR / "test_docs" / "04_50_page_mixed_boundary_stress.pdf",
    "Salesforce (large)": BASE_DIR / "test_docs" / "salesforce_release_notes_3-25-2026.pdf",
}


def main():
    parser = argparse.ArgumentParser(
        description="Run production pipeline on test documents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 run_prod_pipeline.py                    # All documents
  python3 run_prod_pipeline.py --exclude-salesforce  # Skip Salesforce
  python3 run_prod_pipeline.py -v                    # Verbose mode
  python3 run_prod_pipeline.py --include LabReport --include Invoice  # Specific files
        """,
    )
    parser.add_argument(
        "--exclude-salesforce",
        action="store_true",
        help="Skip Salesforce PDF (large document)",
    )
    parser.add_argument(
        "--include",
        action="append",
        dest="include_files",
        help="Only process specified files (can be used multiple times)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available test documents",
    )

    args = parser.parse_args()

    if args.list:
        print("Available test documents:")
        for name, path in TEST_FILES.items():
            size_mb = path.stat().st_size / (1024 * 1024) if path.exists() else 0
            status = "✓" if path.exists() else "✗"
            print(f"  {status} {name:30} ({size_mb:6.1f} MB)")
        return 0

    files_to_process = dict(TEST_FILES)

    if args.exclude_salesforce:
        del files_to_process["Salesforce (large)"]

    if args.include_files:
        filtered = {}
        for include_name in args.include_files:
            for name, path in files_to_process.items():
                if include_name.lower() in name.lower():
                    filtered[name] = path
                    break
        files_to_process = filtered

    if not files_to_process:
        print("No files to process")
        return 1

    print(f"\n{'='*80}")
    print(f"Processing {len(files_to_process)} documents")
    print(f"{'='*80}\n")

    results = []
    total_cost = 0.0

    for i, (name, file_path) in enumerate(files_to_process.items(), 1):
        if not file_path.exists():
            print(f"[{i}/{len(files_to_process)}] ✗ {name} — File not found")
            continue

        print(f"[{i}/{len(files_to_process)}] Processing: {name}")
        print("-" * 80)

        result = run(str(file_path), output_dir=OUTPUT_DIR / file_path.stem, verbose=args.verbose)

        success = result["markdown_path"] is not None
        status = "✓ SUCCESS" if success else "✗ FAILED"

        print(f"\n{status}")
        print(f"  Chunks: {result['chunk_count']}")
        print(f"  Time: {result['elapsed_seconds']:.1f}s")

        if result.get("cost_estimate"):
            cost = result["cost_estimate"]["total_cost"]
            total_cost += cost
            print(f"  Cost: ${cost:.3f} ({result['cost_estimate']['input_tokens']:,} in, "
                  f"{result['cost_estimate']['output_tokens']:,} out)")

        if result["warnings"]:
            print(f"  Warnings: {len(result['warnings'])}")
            for w in result["warnings"][:2]:
                print(f"    - {w}")

        if success:
            md_path = Path(result["markdown_path"])
            md_size = md_path.stat().st_size
            blocks_path = Path(result["raw_blocks_path"])
            blocks_size = blocks_path.stat().st_size
            print(f"  Output: {md_size:,} bytes (Markdown), {blocks_size:,} bytes (blocks)")

        results.append({
            "file": name,
            "success": success,
            "chunks": result["chunk_count"],
            "elapsed": result["elapsed_seconds"],
            "cost": result.get("cost_estimate", {}).get("total_cost"),
            "warnings": len(result["warnings"]),
        })

        print()

    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)

    successful = sum(1 for r in results if r["success"])
    print(f"\nProcessed: {successful}/{len(results)} successful\n")

    for r in results:
        status = "✓" if r["success"] else "✗"
        cost_str = f"${r['cost']:.3f}" if r.get("cost") else "N/A"
        chunks_str = str(r["chunks"]) if r["success"] else "-"
        print(
            f"{status} {r['file']:35} | chunks: {chunks_str:2} | "
            f"cost: {cost_str:8} | time: {r['elapsed']:6.1f}s"
        )

    print(f"\nTotal cost: ${total_cost:.3f}")
    print(f"Results saved to: {OUTPUT_DIR}/")

    return 0 if successful == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
