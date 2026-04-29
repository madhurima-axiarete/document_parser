from __future__ import annotations

import base64
import json
import re
from typing import Optional

from .models import Block, ChunkPlan

_MODEL = "claude-sonnet-4-6"
_MAX_OUTPUT_TOKENS = 24000


def _render_page_png(page, dpi: int = 100) -> bytes:
    """Render a fitz page to PNG bytes, with DPI fallback."""
    import fitz

    _MAX_IMAGE_BYTES = 4 * 1024 * 1024

    for d in (dpi, 72, 50):
        mat = fitz.Matrix(d / 72, d / 72)
        pix = page.get_pixmap(matrix=mat)
        data = pix.tobytes("png")
        if len(data) <= _MAX_IMAGE_BYTES:
            return data

    return data


def _extract_page_native(page) -> str:
    """Extract page as Markdown using native PyMuPDF."""
    try:
        return page.get_text("markdown")
    except Exception:
        return page.get_text("text")


_EXTRACTION_JSON_PROMPT = """You are a precise document content extractor. Extract content from the provided document pages and return ONLY a valid JSON object.

CRITICAL RULES:
1. Return ONLY valid JSON matching this schema. No markdown fences, no preamble, no explanation.
2. Process only TARGET pages (marked with [TARGET]). Context pages marked [CONTEXT ONLY] are for continuity awareness — DO NOT output blocks for them.
3. For each content block, determine block_type from: heading, paragraph, table, figure, header, footer, list_item, code.
4. For tables: encode content as a JSON array of string arrays (rows × columns). Include header row first.
5. Set is_truncated=true if the block appears cut off at the end of your visible page range.
6. Set is_continuation=true if the block appears to begin mid-content (no visible start).
7. For figures/images: write a complete description as content. For charts with readable data, include data in metadata.chart_data.
8. Preserve exact text — do not rephrase, summarize, or infer.
9. confidence: 1.0 for clearly legible text, 0.7-0.9 for partially legible, 0.5 for guessed.

JSON SCHEMA:
{
  "blocks": [
    {
      "block_type": "heading|paragraph|table|figure|header|footer|list_item|code",
      "heading_level": number or null,
      "content": "string",
      "is_truncated": boolean,
      "is_continuation": boolean,
      "confidence": number,
      "page_number": number,
      "metadata": {}
    }
  ]
}
"""


def _parse_json_response(raw_text: str) -> list[dict]:
    """Parse Claude's JSON response with fallback strategies."""
    raw_text = raw_text.strip()

    try:
        data = json.loads(raw_text)
        if isinstance(data, dict) and "blocks" in data:
            return data["blocks"]
        return []
    except json.JSONDecodeError:
        pass

    try:
        start = raw_text.index("{")
        end = raw_text.rindex("}") + 1
        data = json.loads(raw_text[start:end])
        if isinstance(data, dict) and "blocks" in data:
            return data["blocks"]
        return []
    except (ValueError, json.JSONDecodeError):
        pass

    match = re.search(r"```json\s*(.*?)\s*```", raw_text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict) and "blocks" in data:
                return data["blocks"]
            return []
        except json.JSONDecodeError:
            pass

    return []


def extract_chunk(
    fitz_doc,
    chunk_plan: ChunkPlan,
    client,
    source_file: str,
    verbose: bool = False,
) -> tuple[list[Block], Optional[str]]:
    """Extract a single chunk from the document via Claude.

    Returns (blocks, error_message). error_message is None on success.
    """
    import fitz

    target_pages = chunk_plan.target_pages
    context_before = chunk_plan.context_before
    context_after = chunk_plan.context_after

    all_context_pages = context_before + target_pages + context_after

    content_parts: list[dict] = []
    text_buffer = ""

    for page_num in all_context_pages:
        page = fitz_doc[page_num - 1]

        is_target = page_num in target_pages
        page_label_prefix = "[TARGET]" if is_target else "[CONTEXT ONLY]"

        is_vision = (
            chunk_plan.uses_vision
            and page_num in target_pages
        )

        if is_vision:
            if text_buffer:
                content_parts.append({"type": "text", "text": text_buffer})
                text_buffer = ""

            png_bytes = _render_page_png(page)
            content_parts.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.standard_b64encode(png_bytes).decode(),
                    },
                }
            )
            content_parts.append(
                {
                    "type": "text",
                    "text": f"{page_label_prefix} PAGE {page_num}",
                }
            )
        else:
            try:
                page_text = page.get_text("text")
                text_buffer += f"\n\n{page_label_prefix} PAGE {page_num}\n{page_text}"
            except Exception:
                text_buffer += f"\n\n{page_label_prefix} PAGE {page_num}\n[extraction failed]"

    if text_buffer:
        content_parts.append({"type": "text", "text": text_buffer})

    if not content_parts:
        return [], "No content to extract"

    content_parts.insert(0, {"type": "text", "text": _EXTRACTION_JSON_PROMPT})

    try:
        with client.messages.stream(
            model=_MODEL,
            max_tokens=_MAX_OUTPUT_TOKENS,
            messages=[
                {
                    "role": "user",
                    "content": content_parts,
                }
            ],
        ) as stream:
            raw_text = stream.get_final_text()
    except Exception as exc:
        return [], f"API error: {exc}"

    block_dicts = _parse_json_response(raw_text)

    if not block_dicts:
        return [], f"Failed to parse JSON response (length={len(raw_text)})"

    blocks: list[Block] = []
    for block_dict in block_dicts:
        try:
            block = Block(
                block_id=f"{source_file.rsplit('.', 1)[0]}_p{block_dict.get('page_number', 1)}_b{len(blocks):04d}",
                block_type=block_dict.get("block_type", "paragraph"),
                content=block_dict.get("content", ""),
                page_number=block_dict.get("page_number", 1),
                source_file=source_file,
                chunk_id=chunk_plan.chunk_id,
                sequence=0,
                confidence=float(block_dict.get("confidence", 1.0)),
                extraction_method="vision" if chunk_plan.uses_vision else "native",
                heading_level=block_dict.get("heading_level"),
                is_truncated=block_dict.get("is_truncated", False),
                is_continuation=block_dict.get("is_continuation", False),
                bbox=None,
                metadata=block_dict.get("metadata", {}),
            )
            blocks.append(block)
        except Exception:
            pass

    return blocks, None
