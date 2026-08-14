"""
test_table_rendering.py — Unit tests for _render_table() and section-level table validation.

Run:
    python3 test_table_rendering.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from production_pipeline.renderer import _render_table


def _is_valid_gfm_table(text: str) -> bool:
    """Return True if text contains at least one GFM table with header + separator."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    pipe_lines = [l for l in lines if l.startswith("|") and l.endswith("|")]
    sep_lines = [l for l in pipe_lines if all(c in "|-: " for c in l)]
    return len(pipe_lines) >= 2 and len(sep_lines) >= 1


def run_tests() -> int:
    failures = 0

    # ── Test 1: standard 3-column table ──────────────────────────────────────
    raw = json.dumps([
        ["Feature", "Requires Admin Setup", "Notes"],
        ["Feature A", "Yes", "Requires X"],
        ["Feature B", "No", "Auto-enabled"],
    ])
    result = _render_table(raw)
    expected_lines = [
        "| Feature | Requires Admin Setup | Notes |",
        "| --- | --- | --- |",
        "| Feature A | Yes | Requires X |",
        "| Feature B | No | Auto-enabled |",
    ]
    for line in expected_lines:
        if line not in result:
            print(f"FAIL test_standard_table: missing line: {line!r}")
            print(f"  Got:\n{result}")
            failures += 1
            break
    else:
        print("PASS test_standard_table")

    # ── Test 2: empty cells preserved ────────────────────────────────────────
    raw2 = json.dumps([
        ["A", "B", "C"],
        ["x", "", "z"],
        ["", "y", ""],
    ])
    result2 = _render_table(raw2)
    if "| x |  | z |" not in result2 and "| x | | z |" not in result2:
        # Allow either "" → " " or "" → "" in cell rendering
        # What matters is empty cells don't collapse columns
        cells = [row.split("|") for row in result2.splitlines()]
        row_widths = [len([c for c in row if c.strip() != "---"]) for row in cells if len(row) > 2]
        if len(set(row_widths)) > 1:
            print(f"FAIL test_empty_cells: column count inconsistent: {row_widths}")
            print(f"  Got:\n{result2}")
            failures += 1
        else:
            print("PASS test_empty_cells")
    else:
        print("PASS test_empty_cells")

    # ── Test 3: GFM structure (pipe lines + separator) ───────────────────────
    raw3 = json.dumps([["Col1", "Col2"], ["v1", "v2"]])
    result3 = _render_table(raw3)
    if not _is_valid_gfm_table(result3):
        print(f"FAIL test_gfm_structure: not a valid GFM table:\n{result3}")
        failures += 1
    else:
        print("PASS test_gfm_structure")

    # ── Test 4: single-row table (header only) ───────────────────────────────
    raw4 = json.dumps([["Only Header"]])
    result4 = _render_table(raw4)
    if "| Only Header |" not in result4 or "---" not in result4:
        print(f"FAIL test_single_row: expected header + separator:\n{result4}")
        failures += 1
    else:
        print("PASS test_single_row")

    # ── Test 5: empty content returns empty string ────────────────────────────
    result5 = _render_table("[]")
    if result5 != "":
        print(f"FAIL test_empty_table: expected '', got {result5!r}")
        failures += 1
    else:
        print("PASS test_empty_table")

    # ── Test 6: malformed JSON returns empty string ───────────────────────────
    result6 = _render_table("not valid json")
    if result6 != "":
        print(f"FAIL test_malformed_json: expected '', got {result6!r}")
        failures += 1
    else:
        print("PASS test_malformed_json")

    # ── Test 7: row order preserved ──────────────────────────────────────────
    raw7 = json.dumps([["N"], ["1"], ["2"], ["3"]])
    result7 = _render_table(raw7)
    rows = [l for l in result7.splitlines() if l.startswith("|") and "---" not in l]
    values = [r.replace("|", "").strip() for r in rows]
    if values != ["N", "1", "2", "3"]:
        print(f"FAIL test_row_order: expected ['N','1','2','3'], got {values}")
        failures += 1
    else:
        print("PASS test_row_order")

    # ── Test 8: pipe characters inside cell are handled ──────────────────────
    raw8 = json.dumps([["A", "B"], ["has | pipe", "ok"]])
    result8 = _render_table(raw8)
    if not _is_valid_gfm_table(result8):
        print(f"FAIL test_pipe_in_cell: not valid GFM:\n{result8}")
        failures += 1
    else:
        print("PASS test_pipe_in_cell")

    return failures


def validate_processed_doc(doc_dir: str) -> int:
    """Validate that every table block in raw_blocks.json is rendered as GFM in sections/*.md.

    Returns number of validation failures.
    """
    doc_path = Path(doc_dir)
    blocks_path = doc_path / "raw_blocks.json"
    sections_dir = doc_path / "sections"

    if not blocks_path.exists():
        print(f"SKIP {doc_dir}: raw_blocks.json not found")
        return 0
    if not sections_dir.exists():
        print(f"SKIP {doc_dir}: sections/ not found")
        return 0

    blocks = json.loads(blocks_path.read_text(encoding="utf-8"))
    table_blocks = [b for b in blocks if b.get("block_type") == "table"]

    if not table_blocks:
        print(f"  No table blocks in {doc_path.name}")
        return 0

    print(f"\n  {doc_path.name}: {len(table_blocks)} table blocks")

    # Build a map: page_number → [section files covering that page]
    section_files = sorted(sections_dir.glob("*.md"))
    page_to_sections: dict[int, list[Path]] = {}
    for sf in section_files:
        content = sf.read_text(encoding="utf-8")
        # Parse page range from header: *p6* or *p6–12*
        import re
        m = re.search(r'\*p(\d+)(?:–(\d+))?\*', content)
        if m:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else start
            for p in range(start, end + 1):
                page_to_sections.setdefault(p, []).append(sf)

    failures = 0
    warned: set[str] = set()

    for block in table_blocks:
        page = block.get("page_number", 0)
        candidate_files = page_to_sections.get(page, [])

        if not candidate_files:
            if f"p{page}" not in warned:
                print(f"  WARN  page {page}: table block has no section file covering it")
                warned.add(f"p{page}")
            failures += 1
            continue

        found_table = False
        for sf in candidate_files:
            if sf.name in warned:
                continue
            content = sf.read_text(encoding="utf-8")
            if _is_valid_gfm_table(content):
                found_table = True
                break

        if not found_table:
            for sf in candidate_files:
                if sf.name not in warned:
                    print(f"  WARN  {sf.name}: contains table block (p{page}) but no GFM table syntax found")
                    warned.add(sf.name)
                    failures += 1

    if failures == 0:
        print(f"  PASS  all table blocks have GFM table syntax in their section files")

    return failures


if __name__ == "__main__":
    print("=" * 60)
    print("Unit tests: _render_table()")
    print("=" * 60)
    unit_failures = run_tests()

    print()
    print("=" * 60)
    print("Section validation: table blocks → GFM in section files")
    print("=" * 60)

    docs_to_check = [
        "output/production_pipeline/salesforce_first_100_pages",
        "output/production_pipeline/LabReport",
        "output/production_pipeline/04_50_page_mixed_boundary_stress",
    ]

    val_failures = 0
    for doc in docs_to_check:
        val_failures += validate_processed_doc(doc)

    print()
    total = unit_failures + val_failures
    if total == 0:
        print("ALL TESTS PASSED")
    else:
        print(f"{total} FAILURE(S): {unit_failures} unit, {val_failures} validation")

    sys.exit(0 if total == 0 else 1)
