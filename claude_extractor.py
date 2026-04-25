"""
claude_extractor.py

Extracts content from documents using the Anthropic Claude API.
Files are sent directly to Claude — no pre-processing step.
Claude responds in Markdown preserving document order.

Requires: ANTHROPIC_API_KEY env var.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

METHOD = "claude"

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}

# v1 — text extraction only
# _EXTRACTION_PROMPT = """Extract all content from this document and return it as Markdown.

# Rules:
# - Preserve the exact order content appears in the document — top to bottom, do not regroup.
# - Use ## for section headings and ### for sub-headings, matching the document hierarchy.
# - Render label:value pairs as **Label:** Value on their own line.
# - Render tables as Markdown tables with headers and all rows.
# - Copy all text verbatim — do not rephrase, summarize, or add commentary.
# - Do not add any text that is not in the document.
# """

# v2 — text extraction + visual element descriptions
_EXTRACTION_PROMPT = """Extract all content from this document and return it as Markdown.

Rules:
- Preserve the exact order content appears in the document — top to bottom, do not regroup.
- Use ## for section headings and ### for sub-headings, matching the document hierarchy.
- Render label:value pairs as **Label:** Value on their own line.
- Render tables as Markdown tables with headers and all rows.
- Copy all text verbatim — do not rephrase, summarize, or add commentary.
- Do not add any text that is not in the document.
- For every visual element (logo, photograph, diagram, chart, signature, illustration, stamp)
  insert a figure block at the position where it appears in the document:
  > **[Figure]** <description>
  The description must explain what the graphic actually shows: its shape, colors, symbols,
  any text contained within it, spatial layout, and what it represents. Do not just name it —
  describe it as if explaining to someone who cannot see it.
"""

# v3 — text + visual descriptions + block type + spatial position estimates
# Attempts to match Landing AI's output format:
# {content} <!-- block_type, from page N (l=X,t=Y,r=X,b=Y) -->
# _EXTRACTION_PROMPT = """Extract all content from this document and return it as Markdown.

# For every block of content, append a metadata comment at the end of the block on the same line:
# <!-- {block_type}, from page {page} (l={left},t={top},r={right},b={bottom}) -->

# Where:
# - block_type: text | heading | table | figure | marginalia | footnote | page_header | page_footer
#   Use "marginalia" for headers, footers, sidebars, page numbers, and doctor/signatory lines.
# - page: 0-indexed page number (first page = 0)
# - l, t, r, b: estimated normalized bounding box coordinates (0.0 to 1.0) representing
#   left, top, right, bottom edges as fractions of the page width/height.
#   Estimate based on where the block visually appears on the page.
#   Examples: top-left logo ≈ (l=0.05,t=0.02,r=0.30,b=0.10)
#             full-width heading ≈ (l=0.05,t=0.05,r=0.95,b=0.12)
#             bottom-right page number ≈ (l=0.85,t=0.95,r=0.97,b=0.99)

# Content rules:
# - Preserve exact document order — top to bottom, do not regroup.
# - Use ## for section headings and ### for sub-headings.
# - Render label:value pairs as **Label:** Value on their own line.
# - Render tables as Markdown tables with headers and all rows.
# - Copy all text verbatim — do not rephrase, summarize, or add commentary.
# - For every visual element (logo, photograph, diagram, chart, signature, illustration, stamp):
#   Write a figure block ending with the metadata comment:
#   > **[Figure]** <description of shape, colors, symbols, text, layout and meaning> <!-- figure, from page {page} (l=X,t=Y,r=X,b=Y) -->
# """


# ── Claude API calls ───────────────────────────────────────────────────────────


_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 64000  # requires streaming for >16K


def _stream_text(client, messages: list) -> str:
    """Stream a response and return the full text (no output-token ceiling)."""
    with client.messages.stream(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        messages=messages,
    ) as stream:
        return stream.get_final_text()


def _call_with_pdf(client, content: bytes, file_name: str) -> str:
    return _stream_text(client, [{
        "role": "user",
        "content": [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.standard_b64encode(content).decode(),
                },
            },
            {"type": "text", "text": f"{_EXTRACTION_PROMPT}\n\nDOCUMENT: {file_name}"},
        ],
    }])


def _call_with_image(client, content: bytes, ext: str, file_name: str) -> str:
    media_types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                   ".gif": "image/gif", ".webp": "image/webp"}
    return _stream_text(client, [{
        "role": "user",
        "content": [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_types.get(ext, "image/jpeg"),
                    "data": base64.standard_b64encode(content).decode(),
                },
            },
            {"type": "text", "text": f"{_EXTRACTION_PROMPT}\n\nDOCUMENT: {file_name}"},
        ],
    }])


# ── Public interface ───────────────────────────────────────────────────────────


def extract(file_path: str) -> dict:
    """Send file directly to Claude and return the Markdown response."""
    path = Path(file_path)
    ext = path.suffix.lower()
    content = path.read_bytes()

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {
            "file": path.name, "method": METHOD,
            "raw_markdown": "", "raw_text_chars": 0,
            "warnings": ["ANTHROPIC_API_KEY not set — skipping"],
        }

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
    except ImportError:
        return {
            "file": path.name, "method": METHOD,
            "raw_markdown": "", "raw_text_chars": 0,
            "warnings": ["anthropic package not installed"],
        }

    try:
        if ext in _IMAGE_EXTS:
            raw_markdown = _call_with_image(client, content, ext, path.name)
        else:
            raw_markdown = _call_with_pdf(client, content, path.name)
    except Exception as exc:
        return {
            "file": path.name, "method": METHOD,
            "raw_markdown": "", "raw_text_chars": 0,
            "warnings": [f"Claude API error: {exc}"],
        }

    return {
        "file": path.name,
        "method": METHOD,
        "raw_text_chars": len(raw_markdown),
        "raw_markdown": raw_markdown,
        "warnings": [],
    }
