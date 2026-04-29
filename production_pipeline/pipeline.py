from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

from . import normalizer, profiler, chunker, extractor, boundary, renderer, storage, costs
from .models import Block


def run(
    file_path: str | Path,
    output_dir: str | Path | None = None,
    api_key: Optional[str] = None,
    max_retries: int = 2,
    verbose: bool = False,
) -> dict:
    """
    Run the full production pipeline on a document.

    Args:
        file_path: Path to input document
        output_dir: Output directory (default: output/production_pipeline/{stem}/)
        api_key: Anthropic API key (default: env var ANTHROPIC_API_KEY)
        max_retries: Number of retries per chunk on failure
        verbose: Enable verbose logging

    Returns:
        {
            "markdown_path": str,
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
            "markdown_path": None,
            "raw_blocks_path": None,
            "doc_profile": None,
            "chunk_count": 0,
            "cost_estimate": None,
            "warnings": [f"File not found: {file_path}"],
            "elapsed_seconds": time.time() - start_time,
        }

    if api_key is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")

    if not api_key:
        return {
            "markdown_path": None,
            "raw_blocks_path": None,
            "doc_profile": None,
            "chunk_count": 0,
            "cost_estimate": None,
            "warnings": ["ANTHROPIC_API_KEY not set"],
            "elapsed_seconds": time.time() - start_time,
        }

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
    except ImportError:
        return {
            "markdown_path": None,
            "raw_blocks_path": None,
            "doc_profile": None,
            "chunk_count": 0,
            "cost_estimate": None,
            "warnings": ["anthropic package not installed"],
            "elapsed_seconds": time.time() - start_time,
        }

    if output_dir is None:
        stem = file_path.stem
        output_dir = Path("output/production_pipeline") / stem
    else:
        output_dir = Path(output_dir)

    doc = None
    cost_estimate = None
    try:
        if verbose:
            print(f"[1/10] Normalizing {file_path}...")
        doc, file_size_bytes = normalizer.normalize(file_path)

        if verbose:
            print(f"[2/10] Profiling document...")
        doc_profile = profiler.profile_document(doc, file_path.name, file_size_bytes)

        if verbose:
            print(f"[3/10] Planning {doc_profile.total_pages} pages into chunks...")
        chunk_plans = chunker.plan_chunks(doc_profile)

        cost_estimate = costs.estimate_total_cost(doc_profile, chunk_plans)
        if verbose:
            print(f"[4/10] Extracting {len(chunk_plans)} chunks...")
            print(f"       Estimated cost: {costs.format_cost(cost_estimate['total_cost'])} " +
                  f"({cost_estimate['input_tokens']:,} input tokens, " +
                  f"{cost_estimate['output_tokens']:,} output tokens)")

        all_blocks: list[Block] = []
        chunks_to_extract = list(enumerate(chunk_plans))

        while chunks_to_extract:
            i, chunk_plan = chunks_to_extract.pop(0)
            if verbose:
                print(f"  Extracting chunk {i + 1}/{len(chunk_plans)} (pages {chunk_plan.target_pages})...")

            blocks = None
            error_msg = None

            for retry in range(max_retries + 1):
                try:
                    blocks, error = extractor.extract_chunk(
                        doc,
                        chunk_plan,
                        client,
                        file_path.name,
                        verbose=verbose,
                    )
                    if blocks:
                        break
                    elif error:
                        error_msg = error
                except Exception as exc:
                    error_msg = str(exc)
                    if retry < max_retries:
                        import time as time_module
                        backoff = 2 ** retry
                        if verbose:
                            print(f"      Retry {retry + 1}/{max_retries} in {backoff}s...")
                        time_module.sleep(backoff)
                    continue

            if not blocks:
                # Check if chunk size is large (heuristic: >25 pages suggests token overflow)
                chunk_size = len(chunk_plan.target_pages)
                if chunk_size > 25 and "JSON" in error_msg:
                    if verbose:
                        print(f"    Chunk too large ({chunk_size} pages), halving and retrying...")

                    # Dynamically halve the chunk
                    mid = chunk_size // 2
                    first_half_pages = chunk_plan.target_pages[:mid]
                    second_half_pages = chunk_plan.target_pages[mid:]

                    # Create smaller chunk plans
                    first_plan = chunker.ChunkPlan(
                        chunk_index=chunk_plan.chunk_index,
                        chunk_id=f"{chunk_plan.chunk_id}_a",
                        target_pages=first_half_pages,
                        context_before=chunk_plan.context_before,
                        context_after=[first_half_pages[-1] + 1] if first_half_pages[-1] < len(doc) else [],
                        estimated_input_tokens=chunk_plan.estimated_input_tokens // 2,
                        uses_vision=chunk_plan.uses_vision,
                        has_boundary_risk=chunk_plan.has_boundary_risk,
                    )

                    second_plan = chunker.ChunkPlan(
                        chunk_index=chunk_plan.chunk_index,
                        chunk_id=f"{chunk_plan.chunk_id}_b",
                        target_pages=second_half_pages,
                        context_before=[second_half_pages[0] - 1] if second_half_pages[0] > 1 else [],
                        context_after=chunk_plan.context_after,
                        estimated_input_tokens=chunk_plan.estimated_input_tokens // 2,
                        uses_vision=chunk_plan.uses_vision,
                        has_boundary_risk=chunk_plan.has_boundary_risk,
                    )

                    # Re-queue smaller chunks at front
                    chunks_to_extract.insert(0, (i, second_plan))
                    chunks_to_extract.insert(0, (i, first_plan))
                    continue

                msg = f"Chunk {i}: {error_msg or 'unknown error'}"
                warnings.append(msg)
                if verbose:
                    print(f"    WARNING: {msg}")

                placeholder = Block(
                    block_id=f"{file_path.stem}_p{chunk_plan.target_pages[0]}_b0000",
                    block_type="paragraph",
                    content=f"[EXTRACTION FAILED: chunk {i}]",
                    page_number=chunk_plan.target_pages[0],
                    source_file=file_path.name,
                    chunk_id=chunk_plan.chunk_id,
                    sequence=len(all_blocks),
                    confidence=0.0,
                    extraction_method="none",
                )
                blocks = [placeholder]

            all_blocks.extend(blocks)

            storage.save_chunk(chunk_plan, blocks, output_dir)

        if verbose:
            print(f"[5/10] Assigning global sequence numbers...")
        for i, block in enumerate(all_blocks):
            block.sequence = i

        if verbose:
            print(f"[6/10] Reconciling {len(all_blocks)} blocks across chunk boundaries...")
        reconciled_blocks, risks = boundary.reconcile(all_blocks, chunk_plans, client)

        if verbose:
            print(f"[7/10] Saving {len(risks)} boundary risks...")
        storage.save_boundaries(risks, output_dir)

        if verbose:
            print(f"[8/10] Rendering Markdown...")
        markdown = renderer.render(reconciled_blocks)

        if verbose:
            print(f"[9/10] Saving outputs...")
        raw_blocks_path, markdown_path = storage.save_final(
            reconciled_blocks, markdown, output_dir
        )

        storage.save_profiles(doc_profile, chunk_plans, output_dir)

        if verbose:
            print(f"[10/10] Complete!")

        doc.close()

        elapsed = time.time() - start_time
        return {
            "markdown_path": str(markdown_path),
            "raw_blocks_path": str(raw_blocks_path),
            "doc_profile": doc_profile.to_dict(),
            "chunk_count": len(chunk_plans),
            "cost_estimate": cost_estimate,
            "warnings": warnings,
            "elapsed_seconds": elapsed,
        }

    except Exception as exc:
        if doc:
            doc.close()
        return {
            "markdown_path": None,
            "raw_blocks_path": None,
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

    profiles_dir = output_dir / "profiles"
    if not (profiles_dir / "chunk_plans.json").exists():
        return {"success": False, "error": "chunk_plans.json not found"}

    import json
    chunk_plans_data = json.loads((profiles_dir / "chunk_plans.json").read_text())
    chunk_plans = [
        chunker.ChunkPlan(
            chunk_index=c["chunk_index"],
            chunk_id=c["chunk_id"],
            target_pages=c["target_pages"],
            context_before=c.get("context_before", []),
            context_after=c.get("context_after", []),
            estimated_input_tokens=c.get("estimated_input_tokens", 0),
            uses_vision=c.get("uses_vision", False),
            has_boundary_risk=c.get("has_boundary_risk", False),
        )
        for c in chunk_plans_data
    ]

    if chunk_index >= len(chunk_plans):
        return {"success": False, "error": f"Chunk {chunk_index} not found"}

    if api_key is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
    except ImportError:
        return {"success": False, "error": "anthropic package not installed"}

    try:
        doc, _ = normalizer.normalize(file_path)
        chunk_plan = chunk_plans[chunk_index]

        blocks = extractor.extract_chunk(doc, chunk_plan, client, file_path.name)

        if not blocks:
            return {"success": False, "error": "Extraction returned no blocks"}

        storage.save_chunk(chunk_plan, blocks, output_dir)

        raw_blocks_file = output_dir / "raw_blocks.json"
        if raw_blocks_file.exists():
            all_blocks_data = json.loads(raw_blocks_file.read_text())
            all_blocks = [Block.from_dict(b) for b in all_blocks_data]

            for i, block in enumerate(all_blocks):
                if block.chunk_id == chunk_plan.chunk_id:
                    all_blocks[i : i + len(blocks)] = blocks
                    break

            reconciled_blocks, _ = boundary.reconcile(all_blocks, chunk_plans, client)

            markdown = renderer.render(reconciled_blocks)

            markdown_path = output_dir / "output.md"
            markdown_path.write_text(markdown, encoding="utf-8")

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
