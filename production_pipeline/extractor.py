from __future__ import annotations

import base64
import json
import re
from typing import Optional

from .models import Block, ChunkPlan

_MODEL = "claude-sonnet-4-6"
_MAX_OUTPUT_TOKENS = 64000
_TAIL_PAGES = 3  # Pages of previous chunk output passed as context


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


_EXTRACTION_JSON_PROMPT = """You are a precise document content extractor. Extract content from the provided document pages and return ONLY a valid JSON object.

CRITICAL RULES:
1. Return ONLY valid JSON matching this schema. No markdown fences, no preamble, no explanation.
2. Extract content from EVERY page shown. Even blank-looking pages must produce blocks (e.g. a paragraph noting the page is blank).
3. ONE BLOCK PER PAGE PER CONTENT ELEMENT. If a table spans pages 5, 6, and 7, output THREE separate table blocks — one per page — each with the rows visible on that exact page. Never merge content from multiple pages into one block.
4. If PREVIOUSLY EXTRACTED CONTEXT is provided above, use it to understand what content was already extracted. Do NOT re-output those blocks. If a table or list was open at the end of the context, treat the first page here as a continuation (is_continuation=true).
5. For each content block, determine block_type from: heading, paragraph, table, figure, header, footer, list_item, code.
   - header: repeated text at the top of a page (document title, section name).
   - footer: text at the bottom of a page. Set content to the page number if visible (e.g. "42"). Put any other footer text in metadata.footer_text.
6. For tables: encode as a JSON array of string arrays (rows × columns). Include the header row only on the FIRST page of the table. Continuation pages contain only data rows.
7. Set is_truncated=true if a block is cut off at the bottom of the page (continues on next page).
8. Set is_continuation=true if a block begins mid-content (started on a previous page).
9. For FIGURES/IMAGES/CHARTS: write a complete description as content.
   - Data charts: include data as a table in metadata.chart_data AND describe in content.
   - Photos/diagrams/logos: describe everything visible — shape, colors, text, spatial layout.
   - Never use a generic name; always include specific visual details.
10. Preserve exact text. Do not rephrase, summarize, or infer.
11. confidence: 1.0 for clearly legible text, 0.7–0.9 for partially legible, 0.5 for guessed.

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


def _build_tail_context_text(tail_blocks: list[Block]) -> str:
    """Render the tail of the previous chunk as a compact JSON context string."""
    if not tail_blocks:
        return ""

    pages = sorted(set(b.page_number for b in tail_blocks))
    compact = []
    for b in tail_blocks:
        row: dict = {
            "page_number": b.page_number,
            "block_type": b.block_type,
            "is_truncated": b.is_truncated,
        }
        if b.block_type == "heading":
            row["heading_level"] = b.heading_level
            row["content"] = b.content
        elif b.block_type == "table":
            try:
                rows = json.loads(b.content) if isinstance(b.content, str) else b.content
                row["content_preview"] = f"table with {len(rows)} rows; last row: {rows[-1] if rows else []}"
            except Exception:
                row["content_preview"] = str(b.content)[:120]
        else:
            row["content"] = b.content[:200] if b.content else ""
        compact.append(row)

    return (
        f"== PREVIOUSLY EXTRACTED CONTEXT (pages {pages[0]}–{pages[-1]}) ==\n"
        "The following blocks were already extracted from the pages immediately before this chunk.\n"
        "Use them to understand continuation context. Do NOT re-output them.\n\n"
        + json.dumps(compact, indent=2)
        + "\n\n== END OF PREVIOUS CONTEXT ==\n\n"
    )


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


def tail_blocks(blocks: list[Block], n_pages: int = _TAIL_PAGES) -> list[Block]:
    """Return blocks from the last n_pages pages — passed as context to the next chunk."""
    if not blocks:
        return []
    all_pages = sorted(set(b.page_number for b in blocks))
    tail_page_set = set(all_pages[-n_pages:])
    return [b for b in blocks if b.page_number in tail_page_set]


def extract_chunk(
    fitz_doc,
    chunk_plan: ChunkPlan,
    client,
    source_file: str,
    prev_tail_blocks: list[Block] | None = None,
    model: str = _MODEL,
    verbose: bool = False,
    doc_lock=None,
    pages_output_dir: Optional["Path"] = None,
) -> tuple[list[Block], Optional[str], int, int]:
    """Extract a single chunk via Claude, using previous chunk output as context.

    Every page in target_pages is extracted as a full target (PNG image).
    prev_tail_blocks provides structured continuation context as JSON text —
    no duplicate PDF images are sent for context pages.

    Args:
        pages_output_dir: If set, each page PNG is saved to this directory as
            p{page_num:04d}.png and the relative path is stored in each block's
            metadata["page_image"]. Consumers (web UI, notebooks) use this path
            to show the source image. CLI runs ignore it — the path is just metadata.

    Returns (blocks, error_message, input_tokens, output_tokens).
    error_message is None on success.
    """
    from pathlib import Path as _Path

    target_pages = chunk_plan.target_pages
    content_parts: list[dict] = []
    page_png_cache: dict[int, bytes] = {}  # page_num → PNG bytes, reused for saving

    # 1. System prompt
    content_parts.append({"type": "text", "text": _EXTRACTION_JSON_PROMPT})

    # 2. Structured context from previous chunk (compact JSON, not images)
    if prev_tail_blocks:
        context_text = _build_tail_context_text(prev_tail_blocks)
        content_parts.append({"type": "text", "text": context_text})

    # 3. Page images — every page is a TARGET
    for page_num in target_pages:
        if doc_lock:
            with doc_lock:
                page = fitz_doc[page_num - 1]
                png_bytes = _render_page_png(page)
        else:
            page = fitz_doc[page_num - 1]
            png_bytes = _render_page_png(page)

        page_png_cache[page_num] = png_bytes

        content_parts.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.standard_b64encode(png_bytes).decode(),
            },
        })
        content_parts.append({"type": "text", "text": f"PAGE {page_num}"})

    # Save PNGs to disk if visual provenance is enabled
    if pages_output_dir is not None:
        pages_output_dir = _Path(pages_output_dir)
        pages_output_dir.mkdir(parents=True, exist_ok=True)
        for page_num, png_bytes in page_png_cache.items():
            (pages_output_dir / f"p{page_num:04d}.png").write_bytes(png_bytes)

    actual_input_tokens = 0
    actual_output_tokens = 0

    try:
        with client.messages.stream(
            model=model,
            max_tokens=_MAX_OUTPUT_TOKENS,
            messages=[{"role": "user", "content": content_parts}],
        ) as stream:
            final_message = stream.get_final_message()
            raw_text = final_message.content[0].text
            actual_input_tokens = final_message.usage.input_tokens
            actual_output_tokens = final_message.usage.output_tokens
    except Exception as exc:
        return [], f"API error: {exc}", 0, 0

    # Detect truncated response before attempting parse — no fallback can recover a cut-off JSON
    if final_message.stop_reason == "max_tokens":
        return [], f"Response truncated at token limit ({len(raw_text)} chars) — halving needed", actual_input_tokens, actual_output_tokens

    block_dicts = _parse_json_response(raw_text)

    if not block_dicts:
        return [], f"Failed to parse JSON response (length={len(raw_text)})", actual_input_tokens, actual_output_tokens

    # Validate coverage
    target_page_set = set(target_pages)
    extracted_page_set = set(bd.get("page_number", 1) for bd in block_dicts)
    missing = target_page_set - extracted_page_set
    if len(missing) / max(len(target_page_set), 1) >= 0.25 and len(target_page_set) > 1:
        return [], f"Extraction skipped {len(missing)}/{len(target_page_set)} pages {sorted(missing)}—needs halving", actual_input_tokens, actual_output_tokens

    chunk_id_str = str(chunk_plan.chunk_id)
    source_stem = source_file.rsplit(".", 1)[0]
    blocks: list[Block] = []
    last_valid_page: int | None = None

    for bd in block_dicts:
        try:
            content = bd.get("content", "")
            if not isinstance(content, str):
                content = str(content) if content else ""

            metadata = dict(bd.get("metadata") or {})

            # Resolve and validate page_number
            raw_page = bd.get("page_number")
            try:
                raw_page = int(raw_page) if raw_page is not None else None
            except (ValueError, TypeError):
                raw_page = None

            if raw_page is not None and raw_page in target_page_set:
                page_num = raw_page
                last_valid_page = page_num
                block_type = bd.get("block_type", "paragraph")
            elif raw_page is None and last_valid_page is not None:
                # Missing field — infer from previous block (blocks are in page order)
                page_num = last_valid_page
                block_type = bd.get("block_type", "paragraph")
                metadata["page_number_inferred"] = True
            else:
                # Wrong page number (out of target range) — unlocated, excluded from output
                metadata["unlocated_reason"] = (
                    f"page_number={raw_page!r} not in target_pages {sorted(target_page_set)}"
                )
                block = Block(
                    block_id=f"{source_stem}_unlocated_b{len(blocks):04d}",
                    block_type="unlocated",
                    content=content,
                    page_number=0,
                    source_file=source_file,
                    chunk_id=chunk_id_str,
                    sequence=0,
                    confidence=0.0,
                    extraction_method="vision",
                    heading_level=None,
                    is_truncated=False,
                    is_continuation=False,
                    bbox=None,
                    metadata=metadata,
                )
                blocks.append(block)
                continue

            # Visual provenance: record which page PNG this block came from
            if pages_output_dir is not None:
                metadata["page_image"] = f"pages/p{page_num:04d}.png"

            # Capture bbox if Claude returned it (as [x0_pct, y0_pct, x1_pct, y1_pct])
            raw_bbox = bd.get("bbox")
            parsed_bbox = None
            if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) == 4:
                try:
                    parsed_bbox = tuple(float(v) for v in raw_bbox)
                except (ValueError, TypeError):
                    pass

            block = Block(
                block_id=f"{source_stem}_p{page_num}_b{len(blocks):04d}",
                block_type=block_type,
                content=content,
                page_number=page_num,
                source_file=source_file,
                chunk_id=chunk_id_str,
                sequence=0,
                confidence=float(bd.get("confidence", 1.0)),
                extraction_method="vision",
                heading_level=bd.get("heading_level"),
                is_truncated=bd.get("is_truncated", False),
                is_continuation=bd.get("is_continuation", False),
                bbox=parsed_bbox,
                metadata=metadata,
            )
            blocks.append(block)
        except Exception:
            pass

    return blocks, None, actual_input_tokens, actual_output_tokens
