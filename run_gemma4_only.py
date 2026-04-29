"""
run_gemma4_only.py

Runs only the Gemma4 extractor on test documents (except Salesforce).
"""

from pathlib import Path
import gemma4_extractor

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output" / "gemma4"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TEST_FILES = [
    BASE_DIR / "test_docs" / "PerformanceCharts.pdf",
    BASE_DIR / "test_docs" / "LabReport.pdf",
    BASE_DIR / "test_docs" / "Invoice.jpg",
    BASE_DIR / "test_docs" / "AccidentStatement.pdf",
]

for test_file in TEST_FILES:
    if not test_file.exists():
        print(f"[SKIP] {test_file.name} — file not found")
        continue

    print(f"Running Gemma4 on {test_file.name}...", end=" ", flush=True)

    result = gemma4_extractor.extract(str(test_file))

    # Write output
    out_path = OUTPUT_DIR / (test_file.stem + ".md")

    # Build markdown output
    lines = []
    lines.append(f"# {result['file']}")
    lines.append(f"**Method:** {result['method']}")
    if result.get("raw_text_chars"):
        lines.append(f"**Characters extracted:** {result['raw_text_chars']:,}")
    lines.append("")

    if result.get("warnings"):
        lines.append("## ⚠ Warnings")
        for w in result["warnings"]:
            lines.append(f"- {w}")
        lines.append("")

    if result.get("raw_markdown"):
        lines.append(result["raw_markdown"])

    out_path.write_text("\n".join(lines), encoding="utf-8")

    # Summary
    if result.get("raw_markdown"):
        n_lines = len([l for l in result["raw_markdown"].splitlines() if l.strip()])
        print(f"✓ {result['raw_text_chars']:,} chars, {n_lines} lines")
    else:
        first_warn = (result.get("warnings") or ["empty"])[0]
        print(f"✗ {first_warn[:60]}")

print(f"\nOutputs written to: {OUTPUT_DIR}/")
