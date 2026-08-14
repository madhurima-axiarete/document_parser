from __future__ import annotations

from .models import DocProfile, ChunkPlan, PageProfile

# Input-token budgets per chunk type.
# Table-heavy pages produce large JSON output (each page → hundreds of output tokens),
# so we keep those chunks small to stay well under the 64k output-token limit.
# With the new tail-context architecture, context images are not sent, so
# effective input is lower than before — we don't need to reduce budgets further.
_TOKEN_BUDGET_TEXT   = 36_000   # ~10 text pages / chunk
_TOKEN_BUDGET_VISION = 20_000   # ~3–5 image-heavy pages / chunk
_TOKEN_BUDGET_TABLE  =  8_000   # ~3–5 table-heavy pages / chunk  (tight to avoid output overflow)

_MAX_CHUNK_PAGES = 20  # hard cap: never send more than 20 pages in one call
_MIN_CHUNK_PAGES = 1


def _budget_for_page(profile: PageProfile) -> int:
    """Return token budget based on page complexity."""
    if profile.is_table_heavy:
        return _TOKEN_BUDGET_TABLE
    return _TOKEN_BUDGET_VISION


def plan_chunks(doc_profile: DocProfile) -> list[ChunkPlan]:
    """Greedily plan chunks based on token budget and page profiles.

    Returns list of ChunkPlan objects with target and context pages.
    """
    page_profiles = doc_profile.page_profiles
    total_pages = doc_profile.total_pages

    if total_pages == 0:
        return []

    chunks: list[ChunkPlan] = []
    i = 0

    while i < total_pages:
        accumulated_tokens = 0
        chunk_pages: list[int] = []
        j = i

        while j < total_pages and len(chunk_pages) < _MAX_CHUNK_PAGES:
            page_profile = page_profiles[j]
            page_tokens = page_profile.estimated_input_tokens
            budget = _budget_for_page(page_profile)
            if accumulated_tokens + page_tokens > budget and chunk_pages:
                break
            chunk_pages.append(j + 1)
            accumulated_tokens += page_tokens
            j += 1

        # context_before / context_after are no longer used for extraction
        # (replaced by JSON tail blocks from the previous chunk's output).
        # Kept in ChunkPlan for schema compatibility.
        context_before: list[int] = []
        context_after:  list[int] = []

        uses_vision = True

        stem = doc_profile.source_file.rsplit(".", 1)[0]
        chunk_id = f"{stem}_chunk{len(chunks):03d}"

        chunk = ChunkPlan(
            chunk_index=len(chunks),
            chunk_id=chunk_id,
            target_pages=chunk_pages,
            context_before=context_before,
            context_after=context_after,
            estimated_input_tokens=accumulated_tokens,
            uses_vision=uses_vision,
            has_boundary_risk=False,
        )

        chunks.append(chunk)
        i = j

    return chunks
