#!/usr/bin/env python3
"""
query_document.py — Query a processed document using section-based retrieval

Usage:
    python3 query_document.py --doc output/production_pipeline/LabReport/ --toc
    python3 query_document.py --doc output/production_pipeline/LabReport/ --section "results"
    python3 query_document.py --doc output/production_pipeline/LabReport/ --search "test"
    python3 query_document.py --doc output/production_pipeline/LabReport/ --query "what are the key findings?"
    python3 query_document.py --doc output/production_pipeline/LabReport/ --page 2
    python3 query_document.py --list output/production_pipeline/
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


def _find_doc(doc_arg: str) -> tuple[Path, Path, Path]:
    """Load document paths. Returns (index_path, sections_dir, blocks_path).

    Accepts either a document directory or an index.md path.
    """
    path = Path(doc_arg)
    if path.is_file() and path.name == "index.md":
        doc_dir = path.parent
    elif path.is_dir():
        doc_dir = path
    else:
        raise FileNotFoundError(f"Not a valid document path: {doc_arg}")

    index_path = doc_dir / "index.md"
    sections_dir = doc_dir / "sections"
    blocks_path = doc_dir / "raw_blocks.json"

    if not index_path.exists():
        raise FileNotFoundError(f"index.md not found in {doc_dir}")
    if not sections_dir.exists():
        raise FileNotFoundError(f"sections/ directory not found in {doc_dir}")
    if not blocks_path.exists():
        raise FileNotFoundError(f"raw_blocks.json not found in {doc_dir}")

    return index_path, sections_dir, blocks_path


def _read_index(index_path: Path) -> str:
    """Read and return the full index.md content."""
    return index_path.read_text(encoding="utf-8")


def _find_section_files(sections_dir: Path, fragment: str) -> list[Path]:
    """Find section files by filename match (slug or number).

    Returns sorted list of matching section files.
    """
    fragment_lower = fragment.lower()
    matching = []
    for section_file in sorted(sections_dir.glob("*.md")):
        if fragment_lower in section_file.name.lower():
            matching.append(section_file)
    return matching


def _grep_sections(sections_dir: Path, keyword: str) -> list[tuple[str, list[str]]]:
    """Search for keyword across section files.

    Returns list of (filename, matching_lines) tuples.
    """
    keyword_lower = keyword.lower()
    results = []
    for section_file in sorted(sections_dir.glob("*.md")):
        content = section_file.read_text(encoding="utf-8")
        matching_lines = [
            line.strip() for line in content.split("\n")
            if keyword_lower in line.lower() and line.strip()
        ]
        if matching_lines:
            results.append((section_file.name, matching_lines[:5]))  # Top 5 matches per file
    return results


def _ask_claude_for_sections(index_content: str, query: str) -> list[tuple[str, int]]:
    """Ask Claude to score and rank sections by relevance.

    Returns list of (filename, score) tuples sorted by score (highest first).
    Only includes sections with score >= 5. Requests top 3 only.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return []

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Score and rank sections by relevance to: {query}\n\n"
                        f"For each section, output exactly one line: <filename> (score/10)\n"
                        f"Only include sections that directly contain feature details, data, or steps.\n"
                        f"Top 3 only. No other text.\n\n"
                        f"Document index:\n{index_content}"
                    ),
                }
            ],
        )
        raw = response.content[0].text
        # Parse "012_automation.md (9/10)" patterns
        pairs = re.findall(r'(\d{3}_[a-z0-9_]+\.md)\s*\((\d+)/10\)', raw)
        # Sort by score descending, take top 3, filter score < 5
        ranked = sorted(pairs, key=lambda x: int(x[1]), reverse=True)[:3]
        return [(f, int(s)) for f, s in ranked if int(s) >= 5]
    except Exception as e:
        print(f"  [section selection error: {e}]")
        return []


def _ask_claude_answer(context: str, query: str) -> str:
    """Ask Claude to synthesize an answer from full section content."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return "[ANTHROPIC_API_KEY not set. Cannot answer.]"

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Answer the question using ONLY the document sections loaded below.\n\n"
                        f"Rules:\n"
                        f"1. Only use information present in the loaded sections.\n"
                        f"2. Quote specific feature names, numbers, steps, and table values verbatim.\n"
                        f"3. Cite each point as [filename, pN].\n"
                        f"4. If the sections do not contain the answer, say: 'Not found in the loaded sections.'\n"
                        f"5. Do NOT add information from outside the provided sections.\n\n"
                        f"Question: {query}\n\n"
                        f"Loaded sections:\n{context}"
                    ),
                }
            ],
        )
        return response.content[0].text
    except Exception as e:
        return f"Claude answer failed: {e}"


def cmd_toc(index_path: Path) -> None:
    """Print the full index.md (agent's routing map)."""
    index_content = _read_index(index_path)
    print(f"\nTable of Contents — {index_path.parent.name}:\n")
    print(index_content)


def cmd_section(sections_dir: Path, fragment: str) -> None:
    """Find and print section files matching the fragment."""
    matching_files = _find_section_files(sections_dir, fragment)

    if not matching_files:
        print(f"\nNo sections found matching: {fragment!r}")
        return

    print(f"\nSections matching '{fragment}':\n")
    print("=" * 70 + "\n")

    for section_file in matching_files:
        content = section_file.read_text(encoding="utf-8")
        print(f"[{section_file.name}]\n")
        print(content)
        print("\n" + "=" * 70 + "\n")


def cmd_search(sections_dir: Path, keyword: str) -> None:
    """Search for keyword across sections."""
    results = _grep_sections(sections_dir, keyword)

    if not results:
        print(f"\nNo matches found for: {keyword!r}")
        return

    print(f"\nSearching for: {keyword!r}\n")
    print("=" * 70 + "\n")

    for filename, lines in results:
        print(f"[{filename}]")
        for line in lines:
            preview = line[:100].replace("\n", " ")
            print(f"  → {preview}")
        print()

    print("=" * 70)


def cmd_query(index_path: Path, sections_dir: Path, query: str) -> None:
    """Full retrieval loop: read index → Claude picks sections → load → Claude answers."""
    print(f"\nQuery: {query}")
    print("=" * 70)

    # Step 1: Read index
    index_content = _read_index(index_path)

    # Step 2: Ask Claude which sections are relevant
    print("\nIdentifying relevant sections...")
    suggested = _ask_claude_for_sections(index_content, query)
    for filename, score in suggested:
        print(f"  {filename:<50} score={score}/10")
    if not suggested:
        print("  (none)")

    # Step 3: Load full content of each section file
    loaded_sections: list[tuple[str, str]] = []
    all_section_files = {f.name: f for f in sections_dir.glob("*.md")}

    for filename, score in suggested:
        if filename in all_section_files:
            content = all_section_files[filename].read_text(encoding="utf-8")
            loaded_sections.append((filename, content))
        else:
            print(f"  [not found: {filename}]")

    # Fuzzy fallback: if nothing loaded, try substring match on the suggested names
    if not loaded_sections and suggested:
        print("  Trying fuzzy filename match...")
        for filename, score in suggested:
            stem = filename.replace(".md", "")
            matches = [name for name in all_section_files if stem in name or name in stem]
            for match in matches:
                content = all_section_files[match].read_text(encoding="utf-8")
                loaded_sections.append((match, content))
                print(f"  [fuzzy matched: {filename} → {match}]")

    # Hard fallback: grep output.md for query keywords
    fallback_context = None
    if not loaded_sections:
        output_md = index_path.parent / "output.md"
        if output_md.exists():
            print("  [Fallback: searching output.md for query keywords]")
            keywords = query.split()[:3]  # first 3 words as heuristic
            content = output_md.read_text(encoding="utf-8")
            hits = [
                ln.strip() for ln in content.splitlines()
                if any(k.lower() in ln.lower() for k in keywords) and ln.strip()
            ]
            if hits:
                fallback_context = "\n".join(hits[:100])  # top 100 matching lines
                print(f"  Context (fallback grep): {len(fallback_context):,} chars")
                print()
            else:
                print("No content found. Try --search or --toc to explore.")
                return
        else:
            print("No matching section files found. Try --search or --toc to explore.")
            return

    if loaded_sections:
        print(f"  Loaded {len(loaded_sections)} / {len(suggested)} sections")
        # Step 4: Combine full section content as context
        context = "\n\n---\n\n".join(
            f"[{filename}]\n{content}" for filename, content in loaded_sections
        )
    else:
        context = fallback_context

    # Debug: print context size and first 500 chars
    print(f"  Context: {len(context):,} chars sent to Claude")
    print(f"  Preview (first 500 chars):\n  {context[:500].replace(chr(10), chr(10)+'  ')}")
    print()

    # Step 5: Ask Claude to synthesize answer from full section content
    print("=" * 70)
    print("Answer:\n")
    answer = _ask_claude_answer(context, query)
    print(answer)


def cmd_page(blocks_path: Path, page_number: int) -> None:
    """Show all blocks on a given page (debug use)."""
    blocks = json.loads(blocks_path.read_text(encoding="utf-8"))
    page_blocks = [b for b in blocks if b.get("page_number") == page_number]

    if not page_blocks:
        print(f"No blocks found on page {page_number}.")
        return

    print(f"\nPage {page_number} — {len(page_blocks)} blocks:\n")
    for block in page_blocks:
        block_type = block.get("block_type", "unknown")
        content = block.get("content", "")[:200]
        print(f"[{block_type}] {content}")
        print()


def cmd_list(base_dir: str) -> None:
    """List all processed documents with section count."""
    base = Path(base_dir)
    index_files = sorted(base.glob("*/index.md"))

    if not index_files:
        print(f"No processed documents found in {base_dir}")
        return

    print(f"\nProcessed documents in {base_dir}:\n")
    for index_path in index_files:
        doc_name = index_path.parent.name
        sections_dir = index_path.parent / "sections"
        if sections_dir.exists():
            section_count = len(list(sections_dir.glob("*.md")))
        else:
            section_count = 0

        index_size_kb = index_path.stat().st_size / 1024
        print(f"  {doc_name:40} {index_size_kb:8.1f} KB index  ({section_count} sections)")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Query a processed document using section-based retrieval",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 query_document.py --doc output/production_pipeline/LabReport/ --toc
  python3 query_document.py --doc output/production_pipeline/LabReport/ --section "results"
  python3 query_document.py --doc output/production_pipeline/LabReport/ --search "test"
  python3 query_document.py --doc output/production_pipeline/LabReport/ --query "what are the key findings?"
  python3 query_document.py --doc output/production_pipeline/LabReport/ --page 2
  python3 query_document.py --list output/production_pipeline/
        """,
    )
    parser.add_argument("--doc", help="Processed document directory or index.md path")
    parser.add_argument("--toc", action="store_true", help="Print full index.md (agent's routing map)")
    parser.add_argument("--section", metavar="FRAGMENT", help="Find and print section file(s) by name fragment")
    parser.add_argument("--search", metavar="KEYWORD", help="Search for keyword across section files")
    parser.add_argument("--query", "-q", metavar="QUESTION", help="Full retrieval loop: index → Claude picks sections → answer")
    parser.add_argument("--page", type=int, help="Show all blocks on a page (debug use)")
    parser.add_argument("--list", metavar="DIR", help="List all processed documents with section count")

    args = parser.parse_args()

    try:
        if args.list:
            cmd_list(args.list)
            return 0

        if not args.doc:
            parser.print_help()
            return 1

        index_path, sections_dir, blocks_path = _find_doc(args.doc)

        if args.toc:
            cmd_toc(index_path)
        elif args.section:
            cmd_section(sections_dir, args.section)
        elif args.search:
            cmd_search(sections_dir, args.search)
        elif args.query:
            cmd_query(index_path, sections_dir, args.query)
        elif args.page is not None:
            cmd_page(blocks_path, args.page)
        else:
            parser.print_help()
            return 1

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
