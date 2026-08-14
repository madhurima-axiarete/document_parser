from __future__ import annotations

import concurrent.futures
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import normalizer, profiler, chunker, extractor, boundary, renderer, storage, costs
from .models import Block


def _cleanup_output_dir(output_dir: Path) -> None:
    """Remove all artifacts from previous runs in output directory.

    Ensures fresh output with no stale files from prior extractions.
    """
    if not output_dir.exists():
        return

    # Remove specific files/directories that get regenerated
    patterns_to_remove = [
        "*.md",  # index.md, output.md
        "*.json",  # raw_blocks.json
        "sections/",    # all section markdown files
        "chapters/",    # legacy output from old pipeline
        "blocks/",      # legacy per-chunk block files
        "profiles/",    # legacy profiles directory
        "boundaries/",  # legacy boundary analysis
    ]

    for pattern in patterns_to_remove:
        if "/" in pattern:  # directory
            import shutil
            dir_path = output_dir / pattern.rstrip("/")
            if dir_path.exists():
                shutil.rmtree(dir_path)
        else:  # file pattern
            for file_path in output_dir.glob(pattern):
                file_path.unlink()


# Provider support
_PROVIDER_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "bedrock":   "us.anthropic.claude-sonnet-4-5-20250514-v1:0",
    "vertex":    "claude-sonnet-4-5@20250514",
}

def _create_client(provider: str = "anthropic", api_key: Optional[str] = None, **kwargs):
    """Create an Anthropic SDK client for the given provider.

    Returns: (client, model_id)
    """
    import anthropic
    provider = provider.lower()
    if provider not in _PROVIDER_MODELS:
        raise ValueError(f"Unknown provider {provider!r}. Supported: {', '.join(_PROVIDER_MODELS)}. (Azure not supported.)")
    model_id = _PROVIDER_MODELS[provider]

    if provider == "anthropic":
        resolved_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not resolved_key:
            raise ValueError("Anthropic API key not found. Set ANTHROPIC_API_KEY or pass api_key=...")
        return anthropic.Anthropic(api_key=resolved_key), model_id

    elif provider == "bedrock":
        access_key = kwargs.get("aws_access_key") or os.getenv("AWS_ACCESS_KEY_ID")
        secret_key = kwargs.get("aws_secret_key") or os.getenv("AWS_SECRET_ACCESS_KEY")
        region     = kwargs.get("aws_region")     or os.getenv("AWS_DEFAULT_REGION")
        missing = [k for k, v in [("AWS_ACCESS_KEY_ID", access_key), ("AWS_SECRET_ACCESS_KEY", secret_key), ("AWS_DEFAULT_REGION", region)] if not v]
        if missing:
            raise ValueError(f"AWS Bedrock credentials missing: {', '.join(missing)}.")
        return anthropic.AnthropicBedrock(aws_access_key=access_key, aws_secret_key=secret_key, aws_region=region), model_id

    else:  # vertex
        project_id = kwargs.get("vertex_project_id") or os.getenv("VERTEX_PROJECT_ID")
        region     = kwargs.get("vertex_region")      or os.getenv("VERTEX_REGION")
        missing = [k for k, v in [("VERTEX_PROJECT_ID", project_id), ("VERTEX_REGION", region)] if not v]
        if missing:
            raise ValueError(f"Vertex AI credentials missing: {', '.join(missing)}.")
        return anthropic.AnthropicVertex(project_id=project_id, region=region), model_id

def _ts():
    """Return current timestamp for logging."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

_TOKENS_PER_MINUTE = 200_000


class _RateLimiter:
    """Per-run token-bucket rate limiter. Each run() gets its own instance."""

    def __init__(self, tokens_per_minute: int = _TOKENS_PER_MINUTE):
        self._lock = threading.Lock()
        self._tokens_used = 0
        self._window_start = time.time()
        self._limit = tokens_per_minute

    def acquire(self, tokens_needed: int) -> None:
        with self._lock:
            elapsed = time.time() - self._window_start
            if elapsed >= 60:
                self._tokens_used = 0
                self._window_start = time.time()
                elapsed = 0
            available = self._limit - self._tokens_used
            if available < tokens_needed:
                wait_time = 60 - elapsed
                time.sleep(wait_time)
                self._tokens_used = 0
                self._window_start = time.time()
            self._tokens_used += tokens_needed


def run(
    file_path: str | Path,
    output_dir: str | Path | None = None,
    api_key: Optional[str] = None,
    max_retries: int = 2,
    verbose: bool = False,
    provider: str = "anthropic",
    save_page_images: bool = False,
    **provider_kwargs,
) -> dict:
    """
    Run the full production pipeline on a document.

    Args:
        file_path: Path to input document
        output_dir: Output directory (default: output/production_pipeline/{stem}/)
        api_key: Anthropic API key (default: env var ANTHROPIC_API_KEY)
        max_retries: Number of retries per chunk on failure
        verbose: Enable verbose logging
        save_page_images: If True, save each page as a PNG in output/pages/ and
            record the relative path in each block's metadata["page_image"].
            Enables visual provenance — consumers can show the exact source page.
            Off by default (adds disk space proportional to page count).

    Returns:
        {
            "wiki_path": str,
            "raw_blocks_path": str,
            "doc_profile": dict,
            "chunk_count": int,
            "warnings": list[str],
            "elapsed_seconds": float,
        }
    """
    start_time = time.time()
    warnings: list[str] = []

    file_path = Path(file_path)
    if not file_path.exists():
        return {
            "output_path": None,
            "manifest_path": None,
            "raw_blocks_path": None,
            "doc_profile": None,
            "chunk_count": 0,
            "cost_estimate": None,
            "warnings": [f"File not found: {file_path}"],
            "elapsed_seconds": time.time() - start_time,
        }

    try:
        client, model_id = _create_client(provider, api_key=api_key, **provider_kwargs)
    except (ValueError, ImportError) as exc:
        return {
            "output_path": None,
            "manifest_path": None,
            "raw_blocks_path": None,
            "doc_profile": None,
            "chunk_count": 0,
            "cost_estimate": None,
            "warnings": [str(exc)],
            "elapsed_seconds": time.time() - start_time,
        }

    if output_dir is None:
        stem = file_path.stem
        output_dir = Path("output/production_pipeline") / stem
    else:
        output_dir = Path(output_dir)

    # Clean up stale artifacts from previous runs
    _cleanup_output_dir(output_dir)

    doc = None
    cost_estimate = None
    rate_limiter = _RateLimiter()

    try:
        if verbose:
            print(f"[{_ts()}] [1/10] Normalizing {file_path}...")
        doc, file_size_bytes = normalizer.normalize(file_path)

        if verbose:
            print(f"[{_ts()}] [2/10] Profiling document...")
        doc_profile = profiler.profile_document(doc, file_path.name, file_size_bytes)

        if verbose:
            print(f"[{_ts()}] [3/10] Planning {doc_profile.total_pages} pages into chunks...")
        chunk_plans = chunker.plan_chunks(doc_profile)

        if verbose:
            print(f"[{_ts()}] [4/10] Extracting {len(chunk_plans)} chunks (sequential with tail context)...")

        all_blocks: list[Block] = []
        total_input_tokens = 0
        total_output_tokens = 0
        doc_lock = threading.Lock()

        # Visual provenance: pages/ directory (None = disabled)
        pages_dir = (output_dir / "pages") if save_page_images else None
        if pages_dir is not None:
            pages_dir.mkdir(parents=True, exist_ok=True)
            if verbose:
                print(f"[{_ts()}]   Visual provenance enabled → saving page PNGs to {pages_dir}")

        def _call_extractor(plan, prev_tail, label=""):
            """Single API call with retry/backoff. Returns (blocks, in_tok, out_tok)."""
            error_msg = None
            for retry in range(max_retries + 1):
                rate_limiter.acquire(plan.estimated_input_tokens)
                if verbose:
                    retry_sfx = f" (retry {retry})" if retry else ""
                    print(f"[{_ts()}]   {label}pages {plan.target_pages}{retry_sfx} → API call...")
                blocks, error, in_tok, out_tok = extractor.extract_chunk(
                    doc, plan, client, file_path.name,
                    prev_tail_blocks=prev_tail,
                    model=model_id, doc_lock=doc_lock,
                    pages_output_dir=pages_dir,
                )
                if blocks:
                    return blocks, in_tok, out_tok
                error_msg = error or "empty response"
                is_rate_limit = any(x in str(error_msg).lower() for x in ["overload", "rate", "429", "too_many"])
                if is_rate_limit and retry < max_retries:
                    backoff = 2 ** (retry + 1)
                    if verbose:
                        print(f"[{_ts()}]     Rate limited — sleeping {backoff}s...")
                    time.sleep(backoff)
                elif retry < max_retries:
                    if verbose:
                        print(f"[{_ts()}]     Error: {error_msg[:80]} — retrying...")
                else:
                    break
            return None, 0, 0  # signal failure

        def _is_expected_blank(page_num: int) -> bool:
            """True if the profiler says this page has no text, images, or tables."""
            if page_num < 1 or page_num > len(doc_profile.page_profiles):
                return False
            pp = doc_profile.page_profiles[page_num - 1]
            return pp.text_char_count < 20 and pp.image_count == 0 and pp.table_count == 0

        def _extract_sequential(plan, prev_tail, depth=0, label=""):
            """Extract a chunk, halving recursively on JSON parse failure.

            After a successful extraction, checks for missing pages and retries
            each one individually. Inserts extraction_failure placeholder blocks
            for pages that still cannot be extracted (non-blank pages only).
            Surfaces unlocated blocks (invalid page_number) as warnings.

            Halving is sequential: half-A is extracted first, its tail is used
            as context for half-B. This preserves per-page continuity across
            the halved boundary.
            """
            nonlocal total_input_tokens, total_output_tokens
            blocks, in_tok, out_tok = _call_extractor(plan, prev_tail, label)
            total_input_tokens += in_tok
            total_output_tokens += out_tok

            if blocks is not None:
                # Surface any unlocated blocks (invalid page_number) as warnings
                unlocated = [b for b in blocks if b.block_type == "unlocated"]
                if unlocated:
                    warnings.append(
                        f"Chunk {plan.chunk_id}: {len(unlocated)} block(s) had invalid page "
                        f"numbers and are excluded from output — see raw_blocks.json"
                    )

                # Retry missing pages individually
                extracted_pages = {b.page_number for b in blocks if b.block_type != "unlocated"}
                for page in sorted(p for p in plan.target_pages if p not in extracted_pages):
                    if _is_expected_blank(page):
                        continue

                    # Build tail from blocks already extracted before this page
                    pre_blocks = [b for b in blocks if 0 < b.page_number < page]
                    retry_tail = extractor.tail_blocks(pre_blocks)
                    pp = doc_profile.page_profiles[page - 1] if page <= len(doc_profile.page_profiles) else None
                    retry_plan = chunker.ChunkPlan(
                        chunk_index=plan.chunk_index,
                        chunk_id=f"{plan.chunk_id}_retry_p{page}",
                        target_pages=[page],
                        context_before=[], context_after=[],
                        estimated_input_tokens=pp.estimated_input_tokens if pp else 2000,
                        uses_vision=True,
                        has_boundary_risk=False,
                    )
                    retry_blocks, r_in, r_out = _call_extractor(retry_plan, retry_tail, f"[retry p{page}] ")
                    total_input_tokens += r_in
                    total_output_tokens += r_out

                    if retry_blocks:
                        blocks = blocks + retry_blocks
                        if verbose:
                            print(f"[{_ts()}]   Recovered page {page} on retry ({len(retry_blocks)} blocks)")
                    else:
                        placeholder = Block(
                            block_id=f"{file_path.stem}_p{page}_b0000",
                            block_type="extraction_failure",
                            content=f"[Page {page}: extraction failed — no blocks returned after retry]",
                            page_number=page,
                            source_file=file_path.name,
                            chunk_id=plan.chunk_id,
                            sequence=0,
                            confidence=0.0,
                            extraction_method="none",
                        )
                        blocks = blocks + [placeholder]
                        warnings.append(f"Page {page}: extraction failed after retry (non-blank page)")
                        if verbose:
                            print(f"[{_ts()}]   ✗ Page {page} extraction failed — placeholder inserted")

                return blocks

            # Failure — only halve if the chunk is large enough for size to be the likely cause.
            # For <=3 pages that exhausted retries without truncation, failure is content-specific
            # (dense tables, unusual encoding). Halving makes two more calls that also likely fail.
            # Insert placeholders directly instead.
            if len(plan.target_pages) <= 3:
                placeholders = []
                for page in plan.target_pages:
                    warnings.append(
                        f"Page {page}: extraction failed after {max_retries + 1} attempts — placeholder inserted"
                    )
                    if verbose:
                        print(f"[{_ts()}]   ✗ Page {page}: all retries failed, placeholder inserted")
                    placeholders.append(Block(
                        block_id=f"{file_path.stem}_p{page}_b0000",
                        block_type="extraction_failure",
                        content=f"[Page {page}: extraction failed after {max_retries + 1} attempts]",
                        page_number=page,
                        source_file=file_path.name,
                        chunk_id=plan.chunk_id,
                        sequence=0,
                        confidence=0.0,
                        extraction_method="none",
                    ))
                return placeholders

            mid = len(plan.target_pages) // 2
            pages_a = plan.target_pages[:mid]
            pages_b = plan.target_pages[mid:]

            if verbose:
                print(f"[{_ts()}]   Halving → {pages_a} + {pages_b}")

            plan_a = chunker.ChunkPlan(
                chunk_index=plan.chunk_index,
                chunk_id=f"{plan.chunk_id}_a{'_' * depth}",
                target_pages=pages_a,
                context_before=[], context_after=[],
                estimated_input_tokens=plan.estimated_input_tokens // 2,
                uses_vision=plan.uses_vision,
                has_boundary_risk=plan.has_boundary_risk,
            )
            plan_b = chunker.ChunkPlan(
                chunk_index=plan.chunk_index,
                chunk_id=f"{plan.chunk_id}_b{'_' * depth}",
                target_pages=pages_b,
                context_before=[], context_after=[],
                estimated_input_tokens=plan.estimated_input_tokens // 2,
                uses_vision=plan.uses_vision,
                has_boundary_risk=plan.has_boundary_risk,
            )

            blocks_a = _extract_sequential(plan_a, prev_tail, depth + 1, f"[A{depth}] ")
            tail_a = extractor.tail_blocks(blocks_a)
            blocks_b = _extract_sequential(plan_b, tail_a, depth + 1, f"[B{depth}] ")
            return blocks_a + blocks_b

        # ── Sequential extraction with tail passing ───────────────────────────
        prev_tail: list[Block] = []
        for idx, plan in enumerate(chunk_plans):
            label = f"Chunk {idx + 1}/{len(chunk_plans)} "
            chunk_blocks = _extract_sequential(plan, prev_tail, label=label)
            all_blocks.extend(chunk_blocks)
            prev_tail = extractor.tail_blocks(chunk_blocks)
            if verbose:
                print(f"[{_ts()}]   ✓ Chunk {idx + 1}: {len(chunk_blocks)} blocks, "
                      f"pages {sorted(set(b.page_number for b in chunk_blocks))}")

        if verbose:
            print(f"[{_ts()}] [5/10] Assigning global sequence numbers...")
        for i, block in enumerate(all_blocks):
            block.sequence = i

        if verbose:
            print(f"[{_ts()}] [6/10] Light reconciliation ({len(all_blocks)} blocks)...")
        # Seam dedup: drop exact-content duplicates at chunk boundaries,
        # then sort by page number. No LLM reconciliation needed.
        reconciled_blocks, suppressed_headers = boundary.reconcile_seams(all_blocks)

        if verbose:
            print(f"[{_ts()}] [7/10] Normalizing heading levels from TOC...")
        renderer.normalize_headings_from_toc(reconciled_blocks, doc_profile, verbose=verbose)

        if verbose:
            print(f"[{_ts()}] [8/10] Rendering sections...")
        sections, sections_meta, output_md = renderer.render_sections(reconciled_blocks, doc_profile, verbose=verbose)

        if verbose:
            print(f"[{_ts()}] [9/10] Saving outputs...")
        storage.save_sections(sections, output_dir)
        manifest_path = storage.save_manifest(doc_profile, sections_meta, output_dir, suppressed_headers)
        output_path = storage.save_output(output_md, output_dir)
        raw_blocks_path = storage.save_final(reconciled_blocks, output_dir)

        if verbose:
            print(f"[{_ts()}] [10/10] Complete!")

        doc.close()

        elapsed = time.time() - start_time
        real_cost = costs.compute_real_cost(total_input_tokens, total_output_tokens, model_id)

        if verbose:
            print(f"\n[{_ts()}] ✓ SUCCESS")
            print(f"[{_ts()}]   Time: {elapsed:.1f}s")
            print(f"[{_ts()}]   Cost: {costs.format_cost(real_cost['total_cost'])} ({real_cost['input_tokens']:,} in, {real_cost['output_tokens']:,} out)")

        return {
            "output_path": str(output_path),
            "manifest_path": str(manifest_path),
            "raw_blocks_path": str(raw_blocks_path),
            "markdown_path": str(output_path),  # compat alias
            "doc_profile": doc_profile.to_dict(),
            "chunk_count": len(chunk_plans),
            "cost_estimate": real_cost,
            "warnings": warnings,
            "elapsed_seconds": elapsed,
        }

    except Exception as exc:
        if doc:
            doc.close()
        return {
            "output_path": None,
            "manifest_path": None,
            "raw_blocks_path": None,
            "markdown_path": None,
            "doc_profile": None,
            "chunk_count": 0,
            "cost_estimate": None,
            "warnings": [f"Pipeline error: {exc}"],
            "elapsed_seconds": time.time() - start_time,
        }


def rerun_chunk(
    file_path: str | Path,
    chunk_index: int,
    output_dir: str | Path | None = None,
    api_key: Optional[str] = None,
    provider: str = "anthropic",
    **provider_kwargs,
) -> dict:
    """
    Re-run extraction for a single chunk and update outputs.

    Useful for retrying failed chunks without re-processing the entire document.
    """
    file_path = Path(file_path)
    if output_dir is None:
        stem = file_path.stem
        output_dir = Path("output/production_pipeline") / stem
    else:
        output_dir = Path(output_dir)

    import json
    from .models import DocProfile, Block

    # Reconstruct chunk info from raw_blocks.json (chunk_plans.json removed)
    raw_blocks_file = output_dir / "raw_blocks.json"
    if not raw_blocks_file.exists():
        return {"success": False, "error": "raw_blocks.json not found"}

    all_blocks_data = json.loads(raw_blocks_file.read_text())
    all_blocks = [Block.from_dict(b) for b in all_blocks_data]

    # Group blocks by chunk_id to reconstruct chunk boundaries
    chunks_by_id: dict[str, list[Block]] = {}
    for block in all_blocks:
        if block.chunk_id not in chunks_by_id:
            chunks_by_id[block.chunk_id] = []
        chunks_by_id[block.chunk_id].append(block)

    # Build chunk_plans from blocks
    chunk_plans: list[chunker.ChunkPlan] = []
    for chunk_index, (chunk_id, blocks_in_chunk) in enumerate(sorted(chunks_by_id.items())):
        pages = sorted(set(b.page_number for b in blocks_in_chunk))
        chunk_plans.append(chunker.ChunkPlan(
            chunk_index=chunk_index,
            chunk_id=chunk_id,
            target_pages=pages,
            context_before=[],
            context_after=[],
            estimated_input_tokens=0,
            uses_vision=False,
            has_boundary_risk=False,
        ))

    if chunk_index >= len(chunk_plans):
        return {"success": False, "error": f"Chunk {chunk_index} not found"}

    # Load doc_profile from manifest.json
    doc_profile = None
    manifest_file = output_dir / "manifest.json"
    if manifest_file.exists():
        manifest_data = json.loads(manifest_file.read_text())
        # Reconstruct a minimal DocProfile from manifest doc_stats
        from .models import DocProfile, PageProfile, Chapter
        toc = [Chapter.from_dict(c) for c in manifest_data.get("toc", [])]
        stats = manifest_data.get("doc_stats", {})
        doc_profile = DocProfile(
            source_file=manifest_data["source_file"],
            total_pages=manifest_data["total_pages"],
            file_size_bytes=manifest_data.get("file_size_bytes", 0),
            avg_text_chars_per_page=0,
            avg_input_tokens_per_page=stats.get("avg_input_tokens_per_page", 0),
            scanned_page_count=stats.get("scanned_page_count", 0),
            image_heavy_page_count=stats.get("image_heavy_page_count", 0),
            table_heavy_page_count=stats.get("table_heavy_page_count", 0),
            estimated_total_output_chars=0,
            toc=toc,
        )

    try:
        client, model_id = _create_client(provider, api_key=api_key, **provider_kwargs)
    except (ValueError, ImportError) as exc:
        return {"success": False, "error": str(exc)}

    try:
        doc, _ = normalizer.normalize(file_path)
        chunk_plan = chunk_plans[chunk_index]

        blocks, error = extractor.extract_chunk(doc, chunk_plan, client, file_path.name, model=model_id)

        if not blocks:
            return {"success": False, "error": "Extraction returned no blocks"}

        raw_blocks_file = output_dir / "raw_blocks.json"
        if raw_blocks_file.exists():
            all_blocks_data = json.loads(raw_blocks_file.read_text())
            all_blocks = [Block.from_dict(b) for b in all_blocks_data]
            for block in all_blocks:
                if not isinstance(block.chunk_id, str):
                    block.chunk_id = str(block.chunk_id)

            for i, block in enumerate(all_blocks):
                if block.chunk_id == chunk_plan.chunk_id:
                    all_blocks[i : i + len(blocks)] = blocks
                    break

            reconciled_blocks, suppressed_headers = boundary.reconcile_seams(all_blocks)

            if doc_profile:
                sections, sections_meta, output_md = renderer.render_sections(reconciled_blocks, doc_profile)
                storage.save_sections(sections, output_dir)
                storage.save_manifest(doc_profile, sections_meta, output_dir, suppressed_headers)
                storage.save_output(output_md, output_dir)

            raw_blocks_file.write_text(
                json.dumps([b.to_dict() for b in reconciled_blocks], indent=2),
                encoding="utf-8",
            )

        doc.close()
        return {
            "success": True,
            "chunk_index": chunk_index,
            "blocks_extracted": len(blocks),
        }

    except Exception as exc:
        return {"success": False, "error": str(exc)}
