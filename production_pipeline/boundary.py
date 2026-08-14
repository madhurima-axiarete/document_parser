from __future__ import annotations

import difflib
import json
from typing import Optional

from .models import Block, BoundaryRisk, ChunkPlan


def _find_duplicates(blocks: list[Block]) -> None:
    """Annotate near-duplicate blocks with full context metadata. NEVER drops content.

    Sets metadata["duplicate_context"] with:
    - similar_to: original block_id
    - similarity_ratio: 0.0-1.0
    - context_before_pages: blocks from 3 pages before
    - context_after_pages: blocks from 3 pages after
    - reason: why this is likely a duplicate (cross_page_table, boundary_summary, repeated_header, etc.)

    All blocks are preserved. Downstream consumers decide how to weight/use duplicates.
    """
    if len(blocks) < 2:
        return

    for i in range(len(blocks) - 1):
        block_a = blocks[i]
        block_b = blocks[i + 1]

        content_a = str(block_a.content) if not isinstance(block_a.content, str) else block_a.content
        content_b = str(block_b.content) if not isinstance(block_b.content, str) else block_b.content

        if (
            block_a.chunk_id != block_b.chunk_id
            and content_a
            and content_b
        ):
            ratio = difflib.SequenceMatcher(None, content_a, content_b).ratio()
            if ratio > 0.9:
                # Determine reason for duplication by analyzing context
                reason = "boundary_content_similarity"
                if block_a.block_type == "table" and (block_a.is_truncated or block_b.is_continuation):
                    reason = "cross_page_table_continuation"
                elif block_a.block_type in ("header", "footer"):
                    reason = "repeated_header_footer"
                elif block_a.block_type == "paragraph" and block_b.block_type == "paragraph":
                    reason = "boundary_summary_repeated"

                # Collect context: 3 pages before and after
                context_before_page = block_a.page_number - 3
                context_after_page = block_b.page_number + 3

                context_before_ids = [
                    b.block_id for b in blocks[:i]
                    if b.page_number >= context_before_page
                ][-5:]  # Last 5 blocks in context range

                context_after_ids = [
                    b.block_id for b in blocks[i+2:]
                    if b.page_number <= context_after_page
                ][:5]  # First 5 blocks in context range

                # Mark as duplicate with full context (PRESERVE the block)
                block_b.metadata["duplicate_context"] = {
                    "similar_to": block_a.block_id,
                    "similarity_ratio": ratio,
                    "reason": reason,
                    "context_before_blocks": context_before_ids,
                    "context_after_blocks": context_after_ids,
                    "page_distance": block_b.page_number - block_a.page_number,
                    "action": "preserved_with_context_markers"
                }


def _deduplicate_headers_footers(blocks: list[Block]) -> None:
    """Annotate repeated header/footer blocks in metadata.

    Sets metadata["is_repeated_header_footer"] = True on blocks whose exact text
    appears in 3+ header or footer blocks. Does NOT suppress or delete content.
    """
    header_footer_texts: dict[str, list[Block]] = {}
    for block in blocks:
        if block.block_type in ("header", "footer"):
            content_str = str(block.content) if not isinstance(block.content, str) else block.content
            if content_str not in header_footer_texts:
                header_footer_texts[content_str] = []
            header_footer_texts[content_str].append(block)

    for text, matching_blocks in header_footer_texts.items():
        if len(matching_blocks) >= 3:
            for block in matching_blocks:
                block.metadata["is_repeated_header_footer"] = True


def _parse_table_rows(content) -> list | None:
    """Parse table content as JSON or Python-literal (single-quote) format.

    Extraction pipeline may emit either format; both must be handled identically.
    Returns list-of-rows or None if unparseable.
    """
    if isinstance(content, list):
        return content
    if not isinstance(content, str):
        return None
    try:
        return json.loads(content)
    except (json.JSONDecodeError, ValueError):
        pass
    try:
        import ast
        result = ast.literal_eval(content)
        return result if isinstance(result, list) else None
    except Exception:
        return None


def _merge_tables(blocks: list[Block]) -> list[Block]:
    """Merge table blocks that span chunk boundaries.

    Returns updated blocks list.
    """
    result: list[Block] = []
    i = 0

    while i < len(blocks):
        block = blocks[i]

        if (
            i < len(blocks) - 1
            and block.block_type == "table"
            and block.is_truncated
            and blocks[i + 1].block_type == "table"
            and blocks[i + 1].is_continuation
        ):
            rows_a = _parse_table_rows(block.content)
            rows_b = _parse_table_rows(blocks[i + 1].content)

            if rows_a is not None and rows_b is not None and rows_a and rows_b:
                # Remove duplicate boundary row if present
                if rows_a[-1] == rows_b[0]:
                    rows_b = rows_b[1:]

                merged_rows = rows_a + rows_b
                merged_block = Block(
                    block_id=blocks[i + 1].block_id,
                    block_type="table",
                    content=json.dumps(merged_rows),
                    page_number=block.page_number,
                    source_file=block.source_file,
                    chunk_id=blocks[i + 1].chunk_id,
                    sequence=block.sequence,
                    confidence=min(block.confidence, blocks[i + 1].confidence),
                    extraction_method=block.extraction_method,
                    heading_level=None,
                    is_truncated=blocks[i + 1].is_truncated,
                    is_continuation=False,
                    bbox=None,
                    metadata={
                        **block.metadata,
                        "merged_from_chunks": True,
                    },
                )

                result.append(merged_block)
                i += 2
                continue

        result.append(block)
        i += 1

    return result


def _merge_same_header_tables(blocks: list[Block]) -> list[Block]:
    """Merge consecutive table blocks on different pages that share identical header rows.

    Chain-merges across multiple pages: if pages 31, 32, 33 all have the same
    Feature table header, they are merged into one block covering all three pages.
    Uses _parse_table_rows so both JSON and Python-literal formats are handled.
    """
    result = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        if block.block_type != "table":
            result.append(block)
            i += 1
            continue

        rows_a = _parse_table_rows(block.content)
        if rows_a is None or len(rows_a) < 2:
            result.append(block)
            i += 1
            continue

        # Chain-merge: keep consuming next blocks while they're tables on
        # different pages with the same header row, skipping header/footer decoration
        merged_rows = rows_a
        last_page = block.page_number
        last_chunk_id = block.chunk_id
        pages_spanned = [block.page_number]
        skipped_decoration: list[Block] = []  # header/footer blocks to re-emit after merge
        j = i + 1

        while j < len(blocks):
            nxt = blocks[j]
            # Skip page-decoration blocks (headers/footers) between table continuations
            # but collect them to re-emit after the merged table
            if nxt.block_type in ("header", "footer"):
                skipped_decoration.append(nxt)
                j += 1
                continue
            # Any content block that isn't a table (heading, paragraph, etc.) ends the run
            if nxt.block_type != "table":
                break
            if nxt.page_number == last_page:
                break  # second table on same page — different logical table
            # Never re-merge split blocks (they were intentionally split by _split_oversized_table_blocks)
            if nxt.metadata.get("split_from"):
                break
            rows_b = _parse_table_rows(nxt.content)
            if rows_b is None or len(rows_b) < 2:
                break
            if rows_b[0] != rows_a[0]:
                break  # different header — stop
            merged_rows = merged_rows + rows_b[1:]  # skip repeated header row
            last_page = nxt.page_number
            last_chunk_id = nxt.chunk_id
            pages_spanned.append(nxt.page_number)
            j += 1

        if j > i + 1:
            # At least two tables were merged
            merged_block = Block(
                block_id=blocks[j - 1].block_id,
                block_type="table",
                content=json.dumps(merged_rows),
                page_number=block.page_number,
                source_file=block.source_file,
                chunk_id=last_chunk_id,
                sequence=block.sequence,
                confidence=min(b.confidence for b in blocks[i:j]),
                extraction_method=block.extraction_method,
                heading_level=None,
                is_truncated=blocks[j - 1].is_truncated,
                is_continuation=False,
                bbox=None,
                metadata={
                    **block.metadata,
                    "merged_cross_page": True,
                    "page_span": [pages_spanned[0], pages_spanned[-1]],
                    "pages_merged": pages_spanned,
                },
            )
            result.append(merged_block)
            # Re-emit any header/footer decoration that was skipped during merge
            result.extend(skipped_decoration)
            i = j
        else:
            result.append(block)
            i += 1
    return result


def _link_list_continuations(blocks: list[Block]) -> None:
    """Link list items across chunk boundaries.

    Mutates blocks in-place to set continued_from metadata.
    """
    for i in range(len(blocks) - 1):
        block_a = blocks[i]
        block_b = blocks[i + 1]

        if (
            block_a.block_type == "list_item"
            and block_a.is_truncated
            and block_b.block_type == "list_item"
            and block_b.is_continuation
            and block_a.metadata.get("indent_level") == block_b.metadata.get("indent_level")
        ):
            block_b.metadata["continued_from"] = block_a.block_id


def _move_orphaned_headings(blocks: list[Block]) -> list[Block]:
    """If a heading at end of chunk has no body paragraph, move it to next chunk.

    Returns updated blocks list.
    """
    result: list[Block] = []
    i = 0

    while i < len(blocks):
        block = blocks[i]

        if (
            block.block_type == "heading"
            and i < len(blocks) - 1
            and blocks[i + 1].chunk_id != block.chunk_id
        ):
            next_block = blocks[i + 1]
            if next_block.block_type == "paragraph" and not next_block.is_continuation:
                block_copy = Block(
                    block_id=block.block_id,
                    block_type=block.block_type,
                    content=block.content,
                    page_number=block.page_number,
                    source_file=block.source_file,
                    chunk_id=next_block.chunk_id,
                    sequence=block.sequence,
                    confidence=block.confidence,
                    extraction_method=block.extraction_method,
                    heading_level=block.heading_level,
                    is_truncated=block.is_truncated,
                    is_continuation=block.is_continuation,
                    bbox=block.bbox,
                    metadata=block.metadata,
                )
                result.append(block_copy)
                i += 1
                continue

        result.append(block)
        i += 1

    return result


def _query_llm_for_boundary(
    client,
    blocks: list[Block],
    chunk_boundary_index: int,
    model: str = "claude-sonnet-4-6",
) -> Optional[str]:
    """Send compact boundary summary to Claude for ambiguous cases.

    Returns one of: merge_table|remove_duplicate|continue_section|independent|None
    """
    chunk_n_blocks = []
    chunk_n1_blocks = []

    current_chunk_id = None
    for i, block in enumerate(blocks):
        if i < len(blocks) - 1:
            if blocks[i + 1].chunk_id != block.chunk_id:
                current_chunk_id = block.chunk_id
                break

    if not current_chunk_id:
        return None

    for block in blocks:
        if block.chunk_id == current_chunk_id:
            chunk_n_blocks.append(block)
        elif not chunk_n_blocks or block.chunk_id != current_chunk_id:
            chunk_n1_blocks.append(block)

    if len(chunk_n_blocks) < 1 or len(chunk_n1_blocks) < 1:
        return None

    last_3_n = chunk_n_blocks[-3:]
    first_3_n1 = chunk_n1_blocks[:3]

    compact_n = [
        {
            "id": b.block_id,
            "type": b.block_type,
            "content_preview": b.content[:80] if b.content else "",
            "is_truncated": b.is_truncated,
            "is_continuation": b.is_continuation,
        }
        for b in last_3_n
    ]

    compact_n1 = [
        {
            "id": b.block_id,
            "type": b.block_type,
            "content_preview": b.content[:80] if b.content else "",
            "is_truncated": b.is_truncated,
            "is_continuation": b.is_continuation,
        }
        for b in first_3_n1
    ]

    prompt = f"""You are resolving a document chunk boundary. Examine the JSON below and return a decision.

BOUNDARY CONTEXT:
CHUNK_N_LAST_3_BLOCKS: {json.dumps(compact_n)}
CHUNK_N1_FIRST_3_BLOCKS: {json.dumps(compact_n1)}

POSSIBLE DECISIONS:
- "merge_table": the table continues — merge rows across boundary
- "remove_duplicate": the N+1 block is a duplicate of N — suppress it
- "continue_section": the heading in N starts a section that continues in N+1
- "independent": blocks are independent — no action needed

Return ONLY a JSON object: {{"decision": "<one of the above>", "reasoning": "<one sentence>"}}
"""

    try:
        from anthropic import Anthropic

        with client.messages.stream(
            model=model,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            response = stream.get_final_text()

        try:
            data = json.loads(response)
            return data.get("decision")
        except json.JSONDecodeError:
            match_pattern = r'"decision"\s*:\s*"([^"]+)"'
            import re
            match = re.search(match_pattern, response)
            if match:
                return match.group(1)
            return None
    except Exception:
        return None


def _detect_page_numbering_issues(blocks: list[Block]) -> dict:
    """Detect misalignment between document internal page numbers and PDF page numbers.

    Distinguishes between:
    - DOCUMENT NUMBERING GAPS: adjacent PDF pages where footer numbers skip
      (e.g., PDF p15 has footer 11, PDF p16 has footer 13 — the document itself skipped 12)
    - EXTRACTION GAPS: non-adjacent PDF page_numbers in blocks
      (e.g., blocks jump from page_number=15 to page_number=17 — PDF page 16 was never extracted)

    Only extraction gaps indicate data loss. Document numbering gaps are source document issues.
    """
    footer_pages: dict[int, list[int]] = {}
    for b in blocks:
        if b.block_type == "footer" and isinstance(b.content, str) and b.content.isdigit():
            footer_num = int(b.content)
            if footer_num not in footer_pages:
                footer_pages[footer_num] = []
            footer_pages[footer_num].append(b.page_number)

    pdf_pages = sorted(set(b.page_number for b in blocks))
    footer_nums = sorted(footer_pages.keys())

    # Detect gaps in footer numbering — then classify each gap
    footer_gaps = []
    for i in range(len(footer_nums) - 1):
        if footer_nums[i + 1] - footer_nums[i] > 1:
            gap_start = footer_nums[i]
            gap_end = footer_nums[i + 1]

            # Which PDF pages hold these two adjacent footers?
            pdf_page_before = max(footer_pages[gap_start])
            pdf_page_after = min(footer_pages[gap_end])

            # If the PDF pages are adjacent, this is a document numbering issue
            # If PDF pages have a gap between them, this is an extraction gap
            pdf_gap = pdf_page_after - pdf_page_before - 1
            classification = "document_numbering_skip" if pdf_gap == 0 else "extraction_gap"

            footer_gaps.append({
                "footer_before": gap_start,
                "footer_after": gap_end,
                "missing_footer_numbers": list(range(gap_start + 1, gap_end)),
                "pdf_page_before": pdf_page_before,
                "pdf_page_after": pdf_page_after,
                "pdf_pages_between": pdf_gap,
                "classification": classification,
            })

    # Detect genuine extraction gaps: PDF page_numbers that are non-adjacent
    extraction_gaps = []
    for i in range(len(pdf_pages) - 1):
        if pdf_pages[i + 1] - pdf_pages[i] > 1:
            extraction_gaps.append({
                "after_page": pdf_pages[i],
                "before_page": pdf_pages[i + 1],
                "missing_pdf_pages": list(range(pdf_pages[i] + 1, pdf_pages[i + 1])),
            })

    # Detect misalignments (where footer page number ≠ PDF page number)
    misalignments = []
    for footer_num, pdf_pages_list in footer_pages.items():
        for pdf_page in pdf_pages_list:
            if footer_num != pdf_page:
                misalignments.append({
                    "footer_page_number": footer_num,
                    "actual_pdf_page": pdf_page,
                    "offset": pdf_page - footer_num,
                })

    # Summarise: only extraction gaps are actual data loss
    data_loss_risk = any(g["classification"] == "extraction_gap" for g in footer_gaps) or len(extraction_gaps) > 0

    return {
        "internal_footer_numbers": footer_nums,
        "pdf_page_numbers": pdf_pages,
        "total_pages": len(pdf_pages),
        "footer_gaps": footer_gaps,
        "extraction_gaps": extraction_gaps,
        "page_number_misalignments": misalignments,
        "data_loss_risk": data_loss_risk,
        "is_aligned": len(misalignments) == 0 and len(footer_gaps) == 0,
        "note": (
            "document_numbering_skip gaps are source document issues (not extraction errors). "
            "extraction_gap means PDF pages were genuinely not extracted."
        ),
    }


def _insert_missing_pages(blocks: list[Block]) -> list[Block]:
    """Insert minimal placeholder blocks for PDF pages completely absent from extraction.

    A page is 'completely absent' if it has zero blocks but falls between two
    pages that do have blocks. We insert a synthetic footer block (using linear
    interpolation of surrounding footer numbers) so that:
    - _split_oversized_table_blocks can include the page in hollow_runs
    - _synthesize_missing_footer_numbers assigns it a page number
    - The rendered output shows the page marker in sequence

    Only operates when the surrounding pages have a consistent 1:1 footer offset.
    """
    from collections import Counter

    # Build page → footer number map
    page_to_footer: dict[int, int] = {}
    for b in blocks:
        if b.block_type == "footer" and isinstance(b.content, str) and b.content.strip().isdigit():
            page_to_footer[b.page_number] = int(b.content.strip())

    if not page_to_footer:
        return blocks

    # Dominant offset
    offsets = [pdf_p - fn for pdf_p, fn in page_to_footer.items()]
    dominant_offset = Counter(offsets).most_common(1)[0][0]

    # Find all PDF pages present
    present_pages = sorted(set(b.page_number for b in blocks))
    if not present_pages:
        return blocks

    # Find completely absent pages between first and last present page
    first_p, last_p = present_pages[0], present_pages[-1]
    absent_pages = [p for p in range(first_p, last_p + 1) if p not in set(present_pages)]

    if not absent_pages:
        return blocks

    # Use first available block as a template for source_file etc.
    template = blocks[0]

    new_blocks = list(blocks)
    for p in absent_pages:
        inferred_footer = p - dominant_offset
        if inferred_footer <= 0:
            continue

        # Create a minimal placeholder: just a footer block so the page exists
        synthetic_footer = Block(
            block_id=f"synthetic_missing_page_p{p}",
            block_type="footer",
            content=str(inferred_footer),
            page_number=p,
            source_file=template.source_file,
            chunk_id=template.chunk_id,
            sequence=9998,
            confidence=0.5,
            extraction_method="synthetic_inferred",
            heading_level=None,
            is_truncated=False,
            is_continuation=False,
            bbox=None,
            metadata={
                "synthetic_footer": True,
                "missing_page_placeholder": True,
                "inferred_from_offset": dominant_offset,
                "note": "Page was completely absent from extraction output; placeholder inserted",
            },
        )
        new_blocks.append(synthetic_footer)

    # Re-sort by page number
    _TYPE_ORDER = {"header": 0, "heading": 1, "paragraph": 2,
                   "list_item": 3, "figure": 4, "code": 5, "table": 6, "footer": 7}
    new_blocks.sort(key=lambda b: (b.page_number, _TYPE_ORDER.get(b.block_type, 6)))
    return new_blocks


def _split_oversized_table_blocks(blocks: list[Block]) -> list[Block]:
    """Split table blocks that span multiple pages into per-page blocks.

    Symptom: Claude receives pages 11-25 and outputs ONE table block on p11
    with 113 rows instead of 15 separate per-page table blocks.

    Detection: a table block whose page_number has NO following table block
    on p+1, p+2, ... until the next section-start page — but those intermediate
    pages only have header+footer (hollow). This means their table rows were
    rolled into the block on the section-start page.

    Strategy: only split if the immediately following pages are hollow (header+footer
    only) AND their page count × avg_rows_per_page matches the oversized row count.
    Split rows evenly across the hollow run.
    """
    ROWS_PER_PAGE_HEURISTIC = 15  # typical feature-table rows per PDF page

    # Build page → blocks map
    from collections import defaultdict
    page_map: dict[int, list[Block]] = defaultdict(list)
    for b in blocks:
        page_map[b.page_number].append(b)

    all_pdf_pages = sorted(page_map.keys())

    def is_hollow(page: int) -> bool:
        btypes = {b.block_type for b in page_map.get(page, [])}
        return bool(btypes) and btypes <= {"header", "footer"}

    result: list[Block] = []
    processed_pages: set[int] = set()

    for b in blocks:
        if b.block_type != "table" or b.page_number in processed_pages:
            if b.page_number not in processed_pages:
                result.append(b)
            continue

        # Check if following pages are hollow or placeholder — possible split candidates
        # Hollow = only header/footer. Placeholder = synthetic footer only (missing page).
        p = b.page_number
        hollow_run = []
        check_p = p + 1
        max_page = max(page_map.keys()) if page_map else p
        while check_p <= max_page and (check_p not in page_map or is_hollow(check_p)):
            hollow_run.append(check_p)
            check_p += 1

        if not hollow_run:
            result.append(b)
            continue

        # How many rows does this block have?
        rows = _parse_table_rows(b.content)
        if rows is None or len(rows) < 2:
            result.append(b)
            continue

        header_row = rows[0]
        data_rows = rows[1:]
        n_hollow = len(hollow_run)
        total_pages = 1 + n_hollow

        # Only split if rows roughly match expected page count × density
        expected_min = total_pages * 3   # minimum 3 data rows per page
        expected_max = total_pages * 40  # maximum 40 data rows per page

        if not (expected_min <= len(data_rows) <= expected_max):
            result.append(b)
            continue

        # Distribute rows across pages as evenly as possible
        rows_per_page = len(data_rows) // total_pages
        remainder = len(data_rows) % total_pages

        split_blocks = []
        offset = 0
        for page_idx, page_num in enumerate([p] + hollow_run):
            count = rows_per_page + (1 if page_idx < remainder else 0)
            page_rows = data_rows[offset: offset + count]
            offset += count

            if not page_rows:
                continue

            is_first = (page_idx == 0)
            is_last  = (page_idx == total_pages - 1)

            split_block = Block(
                block_id=f"{b.block_id}_split_p{page_num}",
                block_type="table",
                content=json.dumps([header_row] + page_rows if is_first else page_rows),
                page_number=page_num,
                source_file=b.source_file,
                chunk_id=b.chunk_id,
                sequence=b.sequence,
                confidence=b.confidence,
                extraction_method=b.extraction_method,
                heading_level=None,
                # Never set is_truncated/is_continuation on split blocks — those
                # flags are for cross-chunk boundary merging and would cause
                # _merge_tables to immediately undo this split.
                is_truncated=False,
                is_continuation=False,
                bbox=None,
                metadata={
                    **b.metadata,
                    "split_from": b.block_id,
                    "split_page_index": page_idx,
                    "split_total_pages": total_pages,
                },
            )
            split_blocks.append(split_block)

        if split_blocks:
            # The split_blocks go in place of the original oversized block.
            # Header/footer blocks on hollow pages are emitted normally later.
            result.extend(split_blocks)
            processed_pages.add(p)
        else:
            result.append(b)

    # Re-sort so that within each page the canonical order is preserved:
    # header → heading/paragraph/… → table → footer
    # Without this, split blocks (which inherit the source table's sequence)
    # land before the destination page's header/footer blocks.
    _TYPE_ORDER = {"header": 0, "heading": 1, "paragraph": 2,
                   "list_item": 3, "figure": 4, "code": 5,
                   "table": 6, "footer": 7}
    result.sort(key=lambda b: (b.page_number, _TYPE_ORDER.get(b.block_type, 6)))
    return result


def _synthesize_missing_footer_numbers(blocks: list[Block]) -> list[Block]:
    """Synthesize footer page-number blocks for pages where extraction missed them.

    Root cause: pages landing in [CONTEXT ONLY] during chunked extraction do not
    get blocks emitted. If the offset between PDF-page-number and document-footer-
    number is constant across the document, we can infer the missing numbers.

    Algorithm:
    1. Build (pdf_page → footer_number) from existing numeric footer blocks.
    2. Compute the dominant page-number offset (pdf_page - footer_number).
    3. For every PDF page that has content but no numeric footer block,
       synthesize a footer block using the inferred number.
    4. Synthesized blocks are tagged metadata["synthetic_footer"] = True.
    """
    # Map pdf_page → footer number from existing blocks
    page_to_footer: dict[int, int] = {}
    for b in blocks:
        if b.block_type == "footer" and isinstance(b.content, str) and b.content.strip().isdigit():
            page_to_footer[b.page_number] = int(b.content.strip())

    if not page_to_footer:
        return blocks

    # Compute per-page offsets (pdf_page_number - footer_number)
    offsets = [pdf_p - footer_n for pdf_p, footer_n in page_to_footer.items()]
    if not offsets:
        return blocks

    # Use the most common offset as the canonical one
    from collections import Counter
    dominant_offset = Counter(offsets).most_common(1)[0][0]

    # Find all pdf pages that have content but no numeric footer
    pdf_pages_with_content = sorted(set(b.page_number for b in blocks))
    pages_missing_footer = [
        p for p in pdf_pages_with_content
        if p not in page_to_footer
    ]

    if not pages_missing_footer:
        return blocks

    # Build a source-block template per missing page (to borrow metadata)
    page_to_sample_block: dict[int, Block] = {}
    for b in blocks:
        if b.page_number not in page_to_sample_block:
            page_to_sample_block[b.page_number] = b

    # Insert synthetic footer blocks
    synthetic_count = 0
    new_blocks = list(blocks)
    insertions: list[tuple[int, Block]] = []

    for pdf_page in pages_missing_footer:
        inferred_footer = pdf_page - dominant_offset
        if inferred_footer <= 0:
            continue

        sample = page_to_sample_block.get(pdf_page)
        if sample is None:
            continue

        synthetic_footer = Block(
            block_id=f"synthetic_footer_p{pdf_page}",
            block_type="footer",
            content=str(inferred_footer),
            page_number=pdf_page,
            source_file=sample.source_file,
            chunk_id=sample.chunk_id,
            sequence=9999,
            confidence=0.7,
            extraction_method="synthetic_inferred",
            heading_level=None,
            is_truncated=False,
            is_continuation=False,
            bbox=None,
            metadata={
                "synthetic_footer": True,
                "inferred_from_offset": dominant_offset,
                "note": "Footer page number inferred; not present in extraction output",
            },
        )
        insertions.append((pdf_page, synthetic_footer))
        synthetic_count += 1

    if not insertions:
        return blocks

    # Insert synthetic footers at end of each page's blocks, before next page
    result: list[Block] = []
    insertion_map: dict[int, Block] = {pdf_p: blk for pdf_p, blk in insertions}
    last_page_seen: int | None = None

    for b in new_blocks:
        if last_page_seen is not None and b.page_number != last_page_seen:
            # Page boundary: if previous page needed a synthetic footer, insert it
            if last_page_seen in insertion_map:
                result.append(insertion_map[last_page_seen])
        result.append(b)
        last_page_seen = b.page_number

    # Handle final page
    if last_page_seen is not None and last_page_seen in insertion_map:
        result.append(insertion_map[last_page_seen])

    # Re-sort so synthetic footers land after all other content on their page
    _TYPE_ORDER = {"header": 0, "heading": 1, "paragraph": 2,
                   "list_item": 3, "figure": 4, "code": 5,
                   "table": 6, "footer": 7}
    result.sort(key=lambda b: (b.page_number, _TYPE_ORDER.get(b.block_type, 6)))
    return result


def reconcile_seams(blocks: list[Block]) -> tuple[list[Block], list[str]]:
    """Lightweight post-extraction pass for the new tail-context architecture.

    The new extractor passes tail blocks as JSON context, so Claude handles
    continuation and boundary layout during extraction. This function only does:
    1. Sort all blocks by (page_number, block_type priority, sequence)
    2. Drop exact-content duplicates that appear at chunk seams (Claude sometimes
       re-emits the last row of the context it was given)
    3. Mark repeated headers/footers so the renderer can suppress them

    Returns (blocks, suppressed_header_texts) where suppressed_header_texts is
    the list of verbatim header/footer strings marked as repeated — passed through
    to manifest.json for downstream consumers.

    No LLM calls, no complex merging — the extraction already resolved that.
    """
    if not blocks:
        return blocks, []

    # Sort by page number preserving header→content→footer order within each page.
    # Use sequence as tiebreaker so same-type blocks keep extraction order.
    _TYPE_ORDER = {"header": 0, "heading": 1, "paragraph": 2,
                   "list_item": 3, "figure": 4, "code": 5, "table": 6, "footer": 7}
    blocks = sorted(blocks, key=lambda b: (b.page_number, _TYPE_ORDER.get(b.block_type, 6), b.sequence))

    # Drop exact-content duplicates at seams (same block_type, same content, same page)
    result: list[Block] = []
    for i, block in enumerate(blocks):
        if i == 0:
            result.append(block)
            continue
        prev = result[-1]
        if (prev.block_type == block.block_type
                and prev.content == block.content
                and block.page_number == prev.page_number):
            continue  # exact duplicate on same page — skip
        result.append(block)

    # Mark repeated headers/footers (appearing on 3+ pages verbatim)
    _deduplicate_headers_footers(result)

    suppressed_texts = sorted({
        str(b.content)
        for b in result
        if b.block_type in ("header", "footer") and b.metadata.get("is_repeated_header_footer")
    })

    return result, suppressed_texts


def reconcile(blocks: list[Block], chunk_plans: list[ChunkPlan], client=None, model: str = "claude-sonnet-4-6") -> tuple[list[Block], list[BoundaryRisk]]:
    """Reconcile boundaries using rule-based + LLM approaches. NEVER drops blocks.

    Returns (reconciled_blocks, boundary_risks).

    All duplicate/similar blocks are preserved with context metadata. Downstream consumers
    (retrieval, rendering) decide how to weight/use duplicates based on context.
    """
    risks: list[BoundaryRisk] = []

    # Insert placeholder blocks for pages completely absent from extraction
    blocks = _insert_missing_pages(blocks)

    # Split oversized table blocks that Claude rolled across multiple pages into one block
    blocks = _split_oversized_table_blocks(blocks)

    # Synthesize missing footer page numbers before any other processing
    blocks = _synthesize_missing_footer_numbers(blocks)

    # Detect page numbering issues (after synthesis so gaps reflect true missing)
    page_numbering_info = _detect_page_numbering_issues(blocks)
    for block in blocks:
        if not block.metadata.get("page_numbering_info"):
            block.metadata["page_numbering_info"] = page_numbering_info

    _find_duplicates(blocks)
    _deduplicate_headers_footers(blocks)

    blocks = _merge_tables(blocks)
    blocks = _merge_same_header_tables(blocks)
    _link_list_continuations(blocks)
    blocks = _move_orphaned_headings(blocks)

    boundary_risks_found: dict[int, BoundaryRisk] = {}
    for i in range(len(blocks) - 1):
        if blocks[i].is_truncated or blocks[i + 1].is_continuation:
            # Validate chunk_id is string, not list
            if not isinstance(blocks[i].chunk_id, str):
                blocks[i].chunk_id = str(blocks[i].chunk_id)
            if not isinstance(blocks[i + 1].chunk_id, str):
                blocks[i + 1].chunk_id = str(blocks[i + 1].chunk_id)

            if blocks[i].chunk_id != blocks[i + 1].chunk_id:
                risk = BoundaryRisk(
                    chunk_index=i,
                    risk_type="unresolved_continuation",
                    last_block_of_chunk=blocks[i],
                    first_block_of_next_chunk=blocks[i + 1],
                    resolved=False,
                    resolution="unresolved",
                    llm_decision=None,
                )
                boundary_risks_found[i] = risk

    if client and boundary_risks_found:
        for i, risk in boundary_risks_found.items():
            decision = _query_llm_for_boundary(client, blocks, i, model=model)
            if decision == "merge_table":
                risk.resolution = "llm_decision"
                risk.llm_decision = decision
                risk.resolved = True
            elif decision == "continue_section":
                risk.resolution = "llm_decision"
                risk.llm_decision = decision
                risk.resolved = True
            elif decision == "independent":
                risk.resolved = True

    risks = list(boundary_risks_found.values())
    return blocks, risks
