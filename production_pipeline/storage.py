from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .models import Block, DocProfile


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def save_manifest(
    doc_profile: DocProfile,
    sections_meta: list[dict],
    output_dir: Path,
    suppressed_headers: list[str] | None = None,
    page_numbering_audit: dict | None = None,
) -> Path:
    """Write manifest.json (authoritative metadata) and derive index.md from it.

    manifest.json is the single source of truth for document structure, section
    locations, block IDs, and extraction metadata. index.md is a human/LLM-readable
    navigation view generated from manifest — never hand-built separately.

    Returns path to manifest.json.
    """
    _ensure_dir(output_dir)

    manifest = {
        "source_file": doc_profile.source_file,
        "total_pages": doc_profile.total_pages,
        "file_size_bytes": doc_profile.file_size_bytes,
        "extraction_date": date.today().isoformat(),
        "toc": [c.to_dict() for c in doc_profile.toc],
        "doc_stats": {
            "scanned_page_count": doc_profile.scanned_page_count,
            "image_heavy_page_count": doc_profile.image_heavy_page_count,
            "table_heavy_page_count": doc_profile.table_heavy_page_count,
            "avg_input_tokens_per_page": doc_profile.avg_input_tokens_per_page,
        },
        "header_footer_policy": {
            "suppressed_texts": suppressed_headers or [],
            "reason": "repeated on 3+ pages verbatim",
        },
        "page_numbering_audit": page_numbering_audit or {"gaps": [], "misalignments": []},
        "max_heading_level": max((s["heading_level"] for s in sections_meta), default=1),
        "sections": sections_meta,
    }

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    _write_index_from_manifest(manifest, output_dir)

    return manifest_path


def _write_index_from_manifest(manifest: dict, output_dir: Path) -> None:
    """Generate index.md from manifest — hierarchical, indented by heading level."""
    doc_title = Path(manifest["source_file"]).stem.replace("_", " ").replace("-", " ").title()
    lines = [f"# {doc_title}\n"]

    if manifest.get("toc"):
        lines.append("## Table of Contents\n")
        for entry in manifest["toc"]:
            indent = "  " * (entry["level"] - 1)
            lines.append(f"{indent}- {entry['title']} — p{entry['page_number']}")
        lines.append("")

    lines.append("## Sections\n")
    for s in manifest["sections"]:
        level = s.get("heading_level", 1)
        indent = "  " * (level - 1)
        pr = f" — {s['pages']}" if s.get("pages") else ""
        lines.append(f"{indent}- [{s['title']}]({s['filename']}){pr}")

    index_path = output_dir / "index.md"
    index_path.write_text("\n".join(lines), encoding="utf-8")


def save_sections(sections: dict[str, str], output_dir: Path) -> Path:
    """Save per-section markdown files, removing stale files first.

    Returns path to sections/ directory.
    """
    sections_dir = output_dir / "sections"
    _ensure_dir(sections_dir)

    for old_file in sections_dir.rglob("*.md"):
        old_file.unlink()
    for d in sorted(sections_dir.rglob("*"), reverse=True):
        if d.is_dir() and not list(d.iterdir()):
            d.rmdir()

    for filename, content in sections.items():
        section_file = sections_dir / filename
        _ensure_dir(section_file.parent)
        section_file.write_text(content, encoding="utf-8")

    return sections_dir


def save_output(output_md: str, output_dir: Path) -> Path:
    """Save output.md (full document, lossless reconstruction).

    Returns path to output.md.
    """
    _ensure_dir(output_dir)
    path = output_dir / "output.md"
    path.write_text(output_md, encoding="utf-8")
    return path


def save_final(all_blocks: list[Block], output_dir: Path) -> Path:
    """Save raw_blocks.json (structured extraction data for reprocessing/debugging).

    Returns path to raw_blocks.json.
    """
    _ensure_dir(output_dir)
    raw_blocks_file = output_dir / "raw_blocks.json"
    raw_blocks_file.write_text(
        json.dumps([b.to_dict() for b in all_blocks], indent=2), encoding="utf-8"
    )
    return raw_blocks_file
