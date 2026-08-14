#!/usr/bin/env python3
"""Batch runner for production_pipeline on all test documents."""

import sys
from pathlib import Path
from production_pipeline import run
import json


def main():
    test_docs_dir = Path("test_docs")
    output_base_dir = Path("output/production_pipeline")

    if not test_docs_dir.exists():
        print(f"Error: {test_docs_dir} not found")
        return 1

    # Find all documents
    extensions = {".pdf", ".docx", ".pptx", ".xlsx", ".jpg", ".jpeg", ".png"}
    files = sorted(
        f for f in test_docs_dir.iterdir()
        if f.is_file() and f.suffix.lower() in extensions
    )

    if not files:
        print(f"No documents found in {test_docs_dir}")
        return 1

    print(f"Found {len(files)} documents to process\n")
    print("=" * 80)

    results = []

    for i, file_path in enumerate(files, 1):
        print(f"\n[{i}/{len(files)}] Processing: {file_path.name}")
        print("-" * 80)

        output_dir = output_base_dir / file_path.stem

        try:
            result = run(str(file_path), output_dir=str(output_dir), verbose=True)

            # Summarize
            success = result["markdown_path"] is not None
            status = "✓ SUCCESS" if success else "✗ FAILED"
            print(f"\n{status}")
            print(f"  Chunks: {result['chunk_count']}")
            print(f"  Time: {result['elapsed_seconds']:.1f}s")

            if result.get("cost_estimate"):
                cost = result["cost_estimate"]["total_cost"]
                print(f"  Cost: ${cost:.3f} ({result['cost_estimate']['input_tokens']:,} input, "
                      f"{result['cost_estimate']['output_tokens']:,} output tokens)")

            if result["warnings"]:
                print(f"  ⚠️  Unrecoverable Issues: {len(result['warnings'])}")
                for w in result["warnings"][:3]:
                    print(f"    - {w}")

            if success:
                markdown_path = Path(result["markdown_path"])
                md_size = markdown_path.stat().st_size
                blocks_path = Path(result["raw_blocks_path"])
                blocks_size = blocks_path.stat().st_size
                print(f"  Output: {md_size} bytes (Markdown), {blocks_size} bytes (blocks)")

            results.append({
                "file": file_path.name,
                "success": success,
                "chunks": result["chunk_count"],
                "elapsed": result["elapsed_seconds"],
                "warnings": len(result["warnings"]),
                "cost": result.get("cost_estimate", {}).get("total_cost"),
                "markdown_path": result["markdown_path"],
            })

        except Exception as exc:
            print(f"\n✗ ERROR: {exc}")
            results.append({
                "file": file_path.name,
                "success": False,
                "error": str(exc),
            })

    # Summary table
    print("\n" + "=" * 80)
    print("BATCH SUMMARY")
    print("=" * 80)

    successful = sum(1 for r in results if r["success"])
    print(f"\nProcessed: {successful}/{len(files)} successful\n")

    for r in results:
        status = "✓" if r["success"] else "✗"
        if r["success"]:
            cost_str = f"${r['cost']:.3f}" if r.get('cost') else "N/A"
            print(f"{status} {r['file']:35} | chunks: {r['chunks']:2} | cost: {cost_str:8} | time: {r['elapsed']:6.1f}s")
        else:
            print(f"{status} {r['file']:35} | {r.get('error', 'unknown error')}")

    # Save results JSON
    results_file = output_base_dir / "batch_results.json"
    results_file.parent.mkdir(parents=True, exist_ok=True)
    results_file.write_text(json.dumps(results, indent=2))
    print(f"\nResults saved to: {results_file}")

    return 0 if successful == len(files) else 1


if __name__ == "__main__":
    sys.exit(main())
