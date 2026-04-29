from __future__ import annotations

from .models import DocProfile, ChunkPlan

_TOKEN_BUDGET = 36_000
_OVERLAP_PAGES = 1
_MAX_CHUNK_PAGES = 50
_MIN_CHUNK_PAGES = 1


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
            page_tokens = page_profiles[j].estimated_input_tokens
            if accumulated_tokens + page_tokens > _TOKEN_BUDGET and chunk_pages:
                break
            chunk_pages.append(j + 1)
            accumulated_tokens += page_tokens
            j += 1

        context_before = [i] if i > 0 else []
        context_after = [j + 1] if j < total_pages else []

        uses_vision = any(
            page_profiles[p - 1].is_scanned or page_profiles[p - 1].is_image_heavy
            for p in chunk_pages
        )

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
