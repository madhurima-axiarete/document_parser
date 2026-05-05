from __future__ import annotations

import base64
import json
import re
from typing import Optional

from .models import Block, ChunkPlan

_MODEL = "claude-sonnet-4-6"  # Higher 1M token rate limit than Haiku, prevents overloaded errors
_MAX_OUTPUT_TOKENS = 64000  # Model maximum, prevents truncation on large chunks


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
2. Process EVERY TARGET page (marked with [TARGET]). Context pages marked [CONTEXT ONLY] are for continuity awareness — DO NOT output blocks for them.
3. IMPORTANT: Extract content from ALL TARGET pages, even if some pages are mostly blank. Pages that appear empty should still be processed and result in appropriate blocks or be noted as empty.
4. For each content block, determine block_type from: heading, paragraph, table, figure, header, footer, list_item, code.
5. For tables: encode content as a JSON array of string arrays (rows × columns). Include header row first.
6. Set is_truncated=true if the block appears cut off at the end of your visible page range.
7. Set is_continuation=true if the block appears to begin mid-content (no visible start).
8. For FIGURES/IMAGES/CHARTS: write a COMPLETE DESCRIPTION as content.
   - For charts/graphs with legible numeric or categorical data: include data as table in metadata.chart_data AND describe in content (chart type, title, axis labels, color encoding, key annotations, data summary).
   - For photographs, diagrams, sketches, signatures, illustrations, logos, stamps: describe EVERYTHING visible: shape, colors, symbols, text, spatial layout, visual meaning. Describe as if explaining to someone who cannot see it. Do not just name it.
   - NEVER output just a name or generic description—always include specific visual details.
9. Preserve exact text — do not rephrase, summarize, or infer.
10. confidence: 1.0 for clearly legible text, 0.7-0.9 for partially legible, 0.5 for guessed.

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
    model: str = _MODEL,
    verbose: bool = False,
    doc_lock=None,
) -> tuple[list[Block], Optional[str], int, int]:
    """Extract a single chunk from the document via Claude.

    Args:
        fitz_doc: PyMuPDF document object
        chunk_plan: Chunk plan with target pages
        client: Anthropic client
        source_file: Source filename
        model: Model ID
        verbose: Verbose output
        doc_lock: threading.Lock to serialize PyMuPDF reads (fitz not thread-safe)

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
        # Serialize PyMuPDF page access (fitz.Document is not thread-safe)
        if doc_lock:
            with doc_lock:
                page = fitz_doc[page_num - 1]
        else:
            page = fitz_doc[page_num - 1]

        is_target = page_num in target_pages
        page_label_prefix = "[TARGET]" if is_target else "[CONTEXT ONLY]"

        is_vision = page_num in target_pages

        if is_vision:
            if text_buffer:
                content_parts.append({"type": "text", "text": text_buffer})
                text_buffer = ""

            # Render page to PNG (requires page object - keep page access in lock)
            if doc_lock:
                with doc_lock:
                    png_bytes = _render_page_png(page)
            else:
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
                # Extract text (requires page object - keep page access in lock)
                if doc_lock:
                    with doc_lock:
                        page_text = page.get_text("text")
                else:
                    page_text = page.get_text("text")
                text_buffer += f"\n\n{page_label_prefix} PAGE {page_num}\n{page_text}"
            except Exception:
                text_buffer += f"\n\n{page_label_prefix} PAGE {page_num}\n[extraction failed]"

    if text_buffer:
        content_parts.append({"type": "text", "text": text_buffer})

    if not content_parts:
        return [], "No content to extract"

    content_parts.insert(0, {"type": "text", "text": _EXTRACTION_JSON_PROMPT})

    actual_input_tokens = 0
    actual_output_tokens = 0

    try:
        with client.messages.stream(
            model=model,
            max_tokens=_MAX_OUTPUT_TOKENS,
            messages=[
                {
                    "role": "user",
                    "content": content_parts,
                }
            ],
        ) as stream:
            final_message = stream.get_final_message()
            raw_text = final_message.content[0].text
            actual_input_tokens = final_message.usage.input_tokens
            actual_output_tokens = final_message.usage.output_tokens
    except Exception as exc:
        return [], f"API error: {exc}", 0, 0

    block_dicts = _parse_json_response(raw_text)

    if not block_dicts:
        return [], f"Failed to parse JSON response (length={len(raw_text)})", actual_input_tokens, actual_output_tokens

    # Validate that all target pages were extracted
    target_page_set = set(chunk_plan.target_pages)
    extracted_page_set = set(bd.get("page_number", 1) for bd in block_dicts)

    # Check if any target pages are missing (indicating extraction skipped pages)
    # Only fail if we're missing a significant portion (more than 25%) or if extraction is empty
    if extracted_page_set and target_page_set - extracted_page_set:
        missing_count = len(target_page_set - extracted_page_set)
        missing_ratio = missing_count / len(target_page_set)

        # If we're missing 25%+ of pages, try halving the chunk
        if missing_ratio >= 0.25 and len(target_page_set) > 1:
            missing_pages = sorted(target_page_set - extracted_page_set)
            return [], f"Extraction skipped {missing_count}/{len(target_page_set)} pages {missing_pages}—chunk too large, needs halving", actual_input_tokens, actual_output_tokens

    blocks: list[Block] = []
    # Ensure chunk_id is a string
    chunk_id_str = str(chunk_plan.chunk_id) if not isinstance(chunk_plan.chunk_id, str) else chunk_plan.chunk_id

    for block_dict in block_dicts:
        try:
            # Ensure content is a string (defensive against JSON with arrays)
            content = block_dict.get("content", "")
            if not isinstance(content, str):
                content = str(content) if content else ""

            block = Block(
                block_id=f"{source_file.rsplit('.', 1)[0]}_p{block_dict.get('page_number', 1)}_b{len(blocks):04d}",
                block_type=block_dict.get("block_type", "paragraph"),
                content=content,
                page_number=block_dict.get("page_number", 1),
                source_file=source_file,
                chunk_id=chunk_id_str,
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

    return blocks, None, actual_input_tokens, actual_output_tokens
