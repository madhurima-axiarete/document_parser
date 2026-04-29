from __future__ import annotations

import json
from pathlib import Path

from .models import Block, ChunkPlan, DocProfile, BoundaryRisk


def _ensure_dir(path: Path) -> None:
    """Ensure directory exists."""
    path.mkdir(parents=True, exist_ok=True)


def save_chunk(
    chunk_plan: ChunkPlan,
    blocks: list[Block],
    output_dir: Path,
) -> Path:
    """Save raw blocks for a single chunk to JSON.

    Returns path to saved file.
    """
    chunk_dir = output_dir / "blocks"
    _ensure_dir(chunk_dir)

    chunk_file = chunk_dir / f"chunk_{chunk_plan.chunk_index:03d}.json"

    chunk_data = {
        "chunk_id": chunk_plan.chunk_id,
        "chunk_index": chunk_plan.chunk_index,
        "target_pages": chunk_plan.target_pages,
        "context_before": chunk_plan.context_before,
        "context_after": chunk_plan.context_after,
        "blocks": [b.to_dict() for b in blocks],
    }

    chunk_file.write_text(json.dumps(chunk_data, indent=2), encoding="utf-8")
    return chunk_file


def save_profiles(
    doc_profile: DocProfile,
    chunk_plans: list[ChunkPlan],
    output_dir: Path,
) -> None:
    """Save document and chunk profiles to JSON."""
    profiles_dir = output_dir / "profiles"
    _ensure_dir(profiles_dir)

    doc_file = profiles_dir / "doc_profile.json"
    doc_file.write_text(json.dumps(doc_profile.to_dict(), indent=2), encoding="utf-8")

    chunks_file = profiles_dir / "chunk_plans.json"
    chunks_data = [c.to_dict() for c in chunk_plans]
    chunks_file.write_text(json.dumps(chunks_data, indent=2), encoding="utf-8")


def save_boundaries(
    risks: list[BoundaryRisk],
    output_dir: Path,
) -> None:
    """Save boundary risks to JSON."""
    boundaries_dir = output_dir / "boundaries"
    _ensure_dir(boundaries_dir)

    risks_file = boundaries_dir / "boundary_risks.json"
    risks_data = [r.to_dict() for r in risks]
    risks_file.write_text(json.dumps(risks_data, indent=2), encoding="utf-8")


def save_final(
    all_blocks: list[Block],
    markdown: str,
    output_dir: Path,
) -> tuple[Path, Path]:
    """Save final raw blocks and rendered Markdown.

    Returns (raw_blocks_path, markdown_path).
    """
    _ensure_dir(output_dir)

    raw_blocks_file = output_dir / "raw_blocks.json"
    blocks_data = [b.to_dict() for b in all_blocks]
    raw_blocks_file.write_text(json.dumps(blocks_data, indent=2), encoding="utf-8")

    markdown_file = output_dir / "output.md"
    markdown_file.write_text(markdown, encoding="utf-8")

    return raw_blocks_file, markdown_file
