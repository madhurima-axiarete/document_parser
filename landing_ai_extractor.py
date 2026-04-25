"""
landing_ai_extractor.py

Extracts structure from documents using the Landing AI agentic-doc SDK.
Handles PDFs and images (jpg/png) via AI-based layout understanding.

Requires: LANDING_AI_API_KEY env var.
Install:  pip install agentic-doc
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# agentic_doc looks for VISION_AGENT_API_KEY; map from LANDING_AI_API_KEY if needed
if os.getenv("LANDING_AI_API_KEY") and not os.getenv("VISION_AGENT_API_KEY"):
    os.environ["VISION_AGENT_API_KEY"] = os.environ["LANDING_AI_API_KEY"]

METHOD = "landing_ai"


def _blocks_to_structure(chunks: list) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Convert agentic_doc Chunk objects into sections, tables, and KVPs.

    Chunk types: "text", "table", "heading", "figure", "formula", "list", etc.
    Each chunk has:
        chunk.chunk_type  — str
        chunk.text        — markdown text representation
        chunk.grounding   — list of GroundingElement (page, bounding box)
    """
    sections: list[dict] = []
    tables: list[dict] = []
    kvps: list[dict] = []

    current_heading: str | None = None

    for chunk in chunks:
        ctype = getattr(chunk, "chunk_type", "text")
        text = getattr(chunk, "text", "") or ""
        grounding = getattr(chunk, "grounding", [])
        page = grounding[0].page if grounding else None
        source = f"page {page}" if page is not None else None

        if ctype in ("heading", "section_header"):
            current_heading = text.strip()
            sections.append({"title": current_heading, "level": 1, "content": "", "page": page})

        elif ctype == "table":
            # agentic_doc renders tables as Markdown; parse rows from markdown
            rows = _parse_markdown_table(text)
            if rows:
                tables.append({
                    "headers": rows[0],
                    "rows": rows[1:],
                    "source": source or "table",
                    "section": current_heading,
                })

        elif ctype in ("text", "paragraph", "list", "list_item"):
            # Append to the last section's content, or detect KVPs
            if sections:
                sections[-1]["content"] = (sections[-1].get("content", "") + "\n" + text).strip()
            # Try to find inline KVPs (Label: Value on single lines)
            for line in text.splitlines():
                if ":" in line:
                    parts = line.split(":", 1)
                    key, value = parts[0].strip(), parts[1].strip()
                    if key and value and len(key) < 60 and len(value) < 300:
                        kvps.append({"key": key, "value": value, "section": current_heading, "source": source})

        # figures/formulas: skip (text may be a caption, not useful as KVP)

    return sections, tables, kvps


def _parse_markdown_table(md: str) -> list[list[str]]:
    """Parse a markdown table string into a list of rows (each row is a list of cell strings)."""
    rows: list[list[str]] = []
    for line in md.splitlines():
        line = line.strip()
        if not line or set(line.replace("|", "").replace("-", "").replace(" ", "")) == set():
            continue  # skip separator lines
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if any(c for c in cells):
                rows.append(cells)
    return rows


def extract(file_path: str) -> dict:
    """Extract structure from a document using Landing AI agentic-doc."""
    path = Path(file_path)

    api_key = os.getenv("VISION_AGENT_API_KEY") or os.getenv("LANDING_AI_API_KEY")
    if not api_key:
        return {
            "file": path.name,
            "method": METHOD,
            "raw_text_chars": 0,
            "sections": [],
            "tables": [],
            "key_value_pairs": [],
            "blocks": [],
            "warnings": ["LANDING_AI_API_KEY not set — skipping"],
        }

    try:
        from agentic_doc.parse import parse
    except ImportError:
        return {
            "file": path.name,
            "method": METHOD,
            "raw_text_chars": 0,
            "sections": [],
            "tables": [],
            "key_value_pairs": [],
            "blocks": [],
            "warnings": ["agentic-doc package not installed. Run: pip install agentic-doc"],
        }

    warnings: list[str] = []
    try:
        results = parse(str(path))
        # parse() returns a list of ParsedDocument (one per file submitted)
        parsed_doc = results[0] if results else None
        if parsed_doc is None:
            raise ValueError("parse() returned an empty list")
        chunks = getattr(parsed_doc, "chunks", []) or []
        raw_markdown = getattr(parsed_doc, "markdown", "") or ""
    except Exception as exc:
        return {
            "file": path.name,
            "method": METHOD,
            "raw_text_chars": 0,
            "sections": [],
            "tables": [],
            "key_value_pairs": [],
            "blocks": [],
            "raw_markdown": "",
            "warnings": [f"agentic_doc parse error: {exc}"],
        }

    sections, tables, kvps = _blocks_to_structure(chunks)

    # Raw block summary for inspection
    raw_blocks = [
        {
            "type": getattr(c, "chunk_type", "unknown"),
            "text_preview": (getattr(c, "text", "") or "")[:200],
            "page": getattr(c.grounding[0], "page", None) if getattr(c, "grounding", None) else None,
        }
        for c in chunks
    ]

    full_text = "\n".join(getattr(c, "text", "") or "" for c in chunks)

    return {
        "file": path.name,
        "method": METHOD,
        "raw_text_chars": len(full_text),
        "sections": sections,
        "tables": tables,
        "key_value_pairs": kvps,
        "blocks": raw_blocks,
        "raw_markdown": raw_markdown,
        "warnings": warnings,
    }
