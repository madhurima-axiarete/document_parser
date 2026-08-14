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
from datetime import datetime

# Force unbuffered output for real-time progress
sys.stdout = open(sys.stdout.fileno(), mode='w', buffering=1)

def ts():
    """Return current timestamp for logging."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
    parser.add_argument(
        "--provider",
        choices=["anthropic", "bedrock", "vertex"],
        default="anthropic",
        help="API provider (default: anthropic). Credentials: ANTHROPIC_API_KEY | AWS_ACCESS_KEY_ID+AWS_SECRET_ACCESS_KEY+AWS_DEFAULT_REGION | VERTEX_PROJECT_ID+VERTEX_REGION",
    )

    args = parser.parse_args()

    if args.list:
        print(f"[{ts()}] Available test documents:")
        for name, path in TEST_FILES.items():
            size_mb = path.stat().st_size / (1024 * 1024) if path.exists() else 0
            status = "✓" if path.exists() else "✗"
            print(f"[{ts()}]   {status} {name:30} ({size_mb:6.1f} MB)")
        return 0

    files_to_process = dict(TEST_FILES)

    if args.exclude_salesforce:
        del files_to_process["Salesforce (large)"]

    if args.include_files:
        filtered = {}
        for include_name in args.include_files:
            # If it's a full filepath, check if it exists
            if "/" in include_name or include_name.startswith("~"):
                include_path = Path(include_name).expanduser()
                if include_path.exists():
                    filtered[include_path.name] = include_path
                    continue

            # Otherwise try to match against predefined TEST_FILES
            matched = False
            for name, path in files_to_process.items():
                if include_name.lower() in name.lower():
                    filtered[name] = path
                    matched = True
                    break

            # If not found in TEST_FILES, search test_docs/ directory for matching files
            if not matched:
                test_docs_dir = BASE_DIR / "test_docs"
                if test_docs_dir.exists():
                    for file_path in test_docs_dir.glob(f"*{include_name}*"):
                        if file_path.is_file():
                            filtered[file_path.name] = file_path
                            matched = True
                            break
        files_to_process = filtered

    if not files_to_process:
        print(f"[{ts()}] No files to process")
        return 1

    print(f"\n[{ts()}] {'='*80}")
    print(f"[{ts()}] Processing {len(files_to_process)} documents")
    print(f"[{ts()}] {'='*80}\n")

    results = []
    total_cost = 0.0

    for i, (name, file_path) in enumerate(files_to_process.items(), 1):
        if not file_path.exists():
            print(f"[{ts()}] [{i}/{len(files_to_process)}] ✗ {name} — File not found")
            continue

        print(f"[{ts()}] [{i}/{len(files_to_process)}] Processing: {name}")
        print(f"[{ts()}] {'-' * 80}")

        result = run(str(file_path), output_dir=OUTPUT_DIR / file_path.stem, verbose=args.verbose, provider=args.provider)

        success = result["output_path"] is not None
        status = "✓ SUCCESS" if success else "✗ FAILED"

        print(f"\n[{ts()}] {status}")
        print(f"[{ts()}]   Chunks: {result['chunk_count']}")
        print(f"[{ts()}]   Time: {result['elapsed_seconds']:.1f}s")

        if result.get("cost_estimate"):
            cost = result["cost_estimate"]["total_cost"]
            total_cost += cost
            print(f"[{ts()}]   Cost: ${cost:.3f} ({result['cost_estimate']['input_tokens']:,} in, "
                  f"{result['cost_estimate']['output_tokens']:,} out)")

        if result["warnings"]:
            print(f"[{ts()}]   Warnings: {len(result['warnings'])}")
            for w in result["warnings"][:2]:
                print(f"[{ts()}]     - {w}")

        if success:
            output_path = Path(result["output_path"])
            output_size = output_path.stat().st_size
            raw_blocks_path = Path(result["raw_blocks_path"])
            raw_blocks_size = raw_blocks_path.stat().st_size
            print(f"[{ts()}]   Output: {output_size:,} bytes (output.md), {raw_blocks_size:,} bytes (raw_blocks.json)")

        cost_estimate = result.get("cost_estimate")
        results.append({
            "file": name,
            "success": success,
            "chunks": result["chunk_count"],
            "elapsed": result["elapsed_seconds"],
            "cost": cost_estimate.get("total_cost") if cost_estimate else None,
            "warnings": len(result["warnings"]),
        })

        # Cooldown between documents to allow rate limit to reset
        if i < len(files_to_process):
            import time
            print(f"[{ts()}] Cooling down 30s before next document...")
            time.sleep(30)
        else:
            print()

    # Summary
    print(f"[{ts()}] {'=' * 80}")
    print(f"[{ts()}] SUMMARY")
    print(f"[{ts()}] {'=' * 80}")

    successful = sum(1 for r in results if r["success"])
    print(f"\n[{ts()}] Processed: {successful}/{len(results)} successful\n")

    for r in results:
        status = "✓" if r["success"] else "✗"
        cost_str = f"${r['cost']:.3f}" if r.get("cost") else "N/A"
        chunks_str = str(r["chunks"]) if r["success"] else "-"
        print(
            f"[{ts()}] {status} {r['file']:35} | chunks: {chunks_str:2} | "
            f"cost: {cost_str:8} | time: {r['elapsed']:6.1f}s"
        )

    print(f"\n[{ts()}] Total cost: ${total_cost:.3f}")
    print(f"[{ts()}] Results saved to: {OUTPUT_DIR}/")

    return 0 if successful == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
