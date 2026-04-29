from __future__ import annotations

import difflib
import json
from typing import Optional

from .models import Block, BoundaryRisk, ChunkPlan


def _find_duplicates(blocks: list[Block]) -> set[str]:
    """Find duplicate blocks near chunk boundaries using sequence matching.

    Returns set of block_ids to suppress (duplicates in later chunks).
    """
    to_suppress: set[str] = set()

    if len(blocks) < 2:
        return to_suppress

    for i in range(len(blocks) - 1):
        block_a = blocks[i]
        block_b = blocks[i + 1]

        if (
            block_a.chunk_id != block_b.chunk_id
            and block_a.content
            and block_b.content
        ):
            ratio = difflib.SequenceMatcher(None, block_a.content, block_b.content).ratio()
            if ratio > 0.9:
                to_suppress.add(block_b.block_id)

    return to_suppress


def _deduplicate_headers_footers(blocks: list[Block]) -> set[str]:
    """Find headers/footers that repeat across 3+ pages and suppress them.

    Returns set of block_ids to suppress.
    """
    to_suppress: set[str] = set()

    header_footer_texts: dict[str, list[Block]] = {}
    for block in blocks:
        if block.block_type in ("header", "footer"):
            if block.content not in header_footer_texts:
                header_footer_texts[block.content] = []
            header_footer_texts[block.content].append(block)

    for text, matching_blocks in header_footer_texts.items():
        if len(matching_blocks) >= 3:
            for block in matching_blocks:
                to_suppress.add(block.block_id)

    return to_suppress


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
            try:
                rows_a = json.loads(block.content)
                rows_b = json.loads(blocks[i + 1].content)

                if (
                    isinstance(rows_a, list)
                    and isinstance(rows_b, list)
                    and rows_a
                    and rows_b
                ):
                    if len(rows_a) > 0 and len(rows_b) > 0:
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
            except (json.JSONDecodeError, TypeError):
                pass

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
            model="claude-sonnet-4-6",
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


def reconcile(blocks: list[Block], chunk_plans: list[ChunkPlan], client=None) -> tuple[list[Block], list[BoundaryRisk]]:
    """Reconcile boundaries using rule-based + LLM approaches.

    Returns (reconciled_blocks, boundary_risks).
    """
    risks: list[BoundaryRisk] = []

    duplicates = _find_duplicates(blocks)
    headers_footers_suppress = _deduplicate_headers_footers(blocks)

    for block_id in duplicates | headers_footers_suppress:
        for block in blocks:
            if block.block_id == block_id:
                block.metadata["suppress_in_output"] = True

    blocks = _merge_tables(blocks)
    _link_list_continuations(blocks)
    blocks = _move_orphaned_headings(blocks)

    boundary_risks_found: dict[int, BoundaryRisk] = {}
    for i in range(len(blocks) - 1):
        if blocks[i].is_truncated or blocks[i + 1].is_continuation:
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
            decision = _query_llm_for_boundary(client, blocks, i)
            if decision == "merge_table":
                risk.resolution = "llm_decision"
                risk.llm_decision = decision
                risk.resolved = True
            elif decision == "remove_duplicate":
                risk.resolution = "llm_decision"
                risk.llm_decision = decision
                risk.resolved = True
                for block in blocks:
                    if block.block_id == risk.first_block_of_next_chunk.block_id:
                        block.metadata["suppress_in_output"] = True
                        break
            elif decision == "continue_section":
                risk.resolution = "llm_decision"
                risk.llm_decision = decision
                risk.resolved = True
            elif decision == "independent":
                risk.resolved = True

    risks = list(boundary_risks_found.values())
    return blocks, risks
