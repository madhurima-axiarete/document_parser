from __future__ import annotations

import json
import re
from pathlib import Path
from .models import Block, Chapter, DocProfile


def _normalize_title(text: str) -> str:
    """Normalize heading title for TOC matching."""
    text = text.lower()
    text = re.sub(r'\.{2,}\s*\d+\s*$', '', text)  # remove "........ 23" dotted leaders
    text = re.sub(r'\s+\d+\s*$', '', text)  # remove trailing page numbers
    text = re.sub(r'[^\w\s]', ' ', text)  # strip punctuation
    return re.sub(r'\s+', ' ', text).strip()


def normalize_headings_from_toc(
    blocks: list[Block], doc_profile: DocProfile, verbose: bool = False
) -> None:
    """Force heading levels to match native TOC levels where titles align.

    If TOC is empty, use fallback: normalize heading levels document-wide so
    the highest-level headings are consistently H1/H2.

    Mutates blocks in-place.
    """
    # Step 1: Try TOC-based normalization
    if doc_profile.toc:
        toc_map: dict[str, int] = {}
        for chapter in doc_profile.toc:
            key = _normalize_title(chapter.title)
            if key:
                toc_map[key] = max(toc_map.get(key, 0), chapter.level)

        for block in blocks:
            if block.block_type != "heading":
                continue
            key = _normalize_title(block.content)
            if key in toc_map:
                old = block.heading_level or 2
                new = toc_map[key]
                if old != new:
                    if verbose:
                        print(f"  {block.content[:60]}: H{old} → H{new} via TOC normalization")
                    block.metadata["original_heading_level"] = old
                    block.metadata["heading_level_normalized_by"] = "toc"
                    block.heading_level = new
        return

    # Step 2: Fallback — normalize heading levels document-wide
    # Collect unique heading levels and remap them so highest becomes H1
    heading_blocks = [b for b in blocks if b.block_type == "heading"]
    if not heading_blocks:
        return

    unique_levels = sorted(set(b.heading_level or 2 for b in heading_blocks))
    if len(unique_levels) == 1:
        return  # All headings at same level, no need to normalize

    # Map original levels to normalized levels: highest → 1, next → 2, etc.
    level_map = {level: i + 1 for i, level in enumerate(unique_levels)}

    for block in heading_blocks:
        old_level = block.heading_level or 2
        new_level = level_map.get(old_level, old_level)
        if old_level != new_level:
            if verbose:
                print(f"  {block.content[:60]}: H{old_level} → H{new_level} via fallback normalization")
            block.metadata["original_heading_level"] = old_level
            block.metadata["heading_level_normalized_by"] = "fallback"
            block.heading_level = new_level


def _is_valid_gfm_table(text: str) -> bool:
    """Return True if text contains at least one proper GFM table (pipe lines + separator)."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    pipe_lines = [l for l in lines if l.startswith("|") and l.endswith("|")]
    sep_lines = [l for l in pipe_lines if all(c in "|-: " for c in l)]
    return len(pipe_lines) >= 2 and len(sep_lines) >= 1


def _render_table(content) -> str:
    """Render a table JSON into GFM markdown table format."""
    try:
        if isinstance(content, str):
            try:
                rows = json.loads(content)
            except json.JSONDecodeError:
                # Fallback: try Python literal syntax (single quotes)
                import ast
                rows = ast.literal_eval(content)
        else:
            rows = content

        if not rows:
            return ""

        if not isinstance(rows, list) or not rows[0]:
            return ""

        header = "| " + " | ".join(str(c).strip() for c in rows[0]) + " |"
        separator = "| " + " | ".join("---" for _ in rows[0]) + " |"

        body_lines = []
        for row in rows[1:]:
            row_str = "| " + " | ".join(str(c).strip() for c in row) + " |"
            body_lines.append(row_str)

        return "\n".join([header, separator] + body_lines)
    except (json.JSONDecodeError, TypeError, IndexError, ValueError, SyntaxError):
        return ""


def render(blocks: list[Block], add_page_breaks: bool = True, initial_heading_level: int = 0) -> str:
    """Convert list of Block objects to final Markdown string.

    Applies type-specific rendering, page break markers, heading hierarchy enforcement,
    and post-processing cleanup to remove residual footer/header noise.
    """
    output_parts: list[str] = []
    last_page: int | None = None
    last_heading_level: int = initial_heading_level

    for block in blocks:
        # Page break marker: inject --- when page changes
        if add_page_breaks and last_page is not None and block.page_number != last_page:
            output_parts.append("---")
        last_page = block.page_number

        rendered = ""

        if block.block_type == "heading":
            level = block.heading_level or 2
            # Heading hierarchy enforcement: cannot skip levels
            if last_heading_level > 0:
                level = min(level, last_heading_level + 1)
            last_heading_level = level
            rendered = "#" * level + " " + block.content
        elif block.block_type == "paragraph":
            rendered = block.content
        elif block.block_type == "table":
            rendered = _render_table(block.content)
        elif block.block_type == "figure":
            rendered = "> **[Figure]** " + block.content
        elif block.block_type == "list_item":
            indent_level = block.metadata.get("indent_level", 0)
            rendered = "  " * indent_level + "- " + block.content
        elif block.block_type == "code":
            rendered = "```\n" + block.content + "\n```"
        elif block.block_type in ("header", "footer"):
            if not block.metadata.get("is_repeated_header_footer", False):
                rendered = f"*{block.content}*"
        elif block.block_type == "unlocated":
            continue  # no valid page — excluded from all output
        else:
            rendered = block.content

        if rendered:
            output_parts.append(rendered)

    markdown = "\n\n".join(output_parts)
    return markdown




def _get_context_blocks(blocks: list[Block], section_heading_idx: int, section_end_idx: int, context_pages: int = 3) -> tuple[list[int], list[int]]:
    """Get block indices for context before and after a section.

    Context window = 3 pages before section starts, 3 pages after section ends.
    Never extends into another major heading's territory.
    """
    section_start_page = blocks[section_heading_idx].page_number
    section_end_page = blocks[section_end_idx - 1].page_number if section_end_idx > 0 else section_start_page

    # Context before: from (start_page - 3) until section heading
    context_before_start_page = section_start_page - context_pages
    context_before_indices = []
    for i in range(section_heading_idx - 1, -1, -1):
        if blocks[i].page_number >= context_before_start_page:
            context_before_indices.insert(0, i)
        else:
            break

    # Context after: from (end_page + 1) until (end_page + 3)
    context_after_end_page = section_end_page + context_pages
    context_after_indices = []
    for i in range(section_end_idx, len(blocks)):
        if blocks[i].page_number <= context_after_end_page:
            context_after_indices.append(i)
        else:
            break

    return context_before_indices, context_after_indices


_SECTION_LEVELS = frozenset({1, 2, 3})
_EXCLUDE_TYPES  = frozenset({"unlocated", "extraction_failure"})


def render_sections(
    blocks: list[Block],
    doc_profile,
    verbose: bool = False,
    context_pages: int = 3,
) -> tuple[dict[str, str], list[dict], str]:
    """Render document into a capped H1/H2/H3 section hierarchy.

    Rules:
    - H1, H2, H3 each get their own file under sections/.
    - H4+ headings and their content are absorbed into the nearest ancestor file.
    - Every block belongs to exactly one file — no duplicated content.
    - H1 file body: blocks between the H1 and its first H2 child.
    - H2 file body: blocks between the H2 and its first H3 child.
    - H3 file body: all blocks within its scope including any H4+ descendants.
    - Preamble blocks (before the first H1/H2/H3) are prepended to the first file.
    """
    doc_title = Path(doc_profile.source_file).stem.replace("_", " ").replace("-", " ").title()

    def _slug(title: str) -> str:
        s = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
        return s[:40]

    def _page_range(blks: list[Block]) -> str:
        if not blks:
            return ""
        pages = sorted({b.page_number for b in blks})
        return f"p{pages[0]}–{pages[-1]}" if len(pages) > 1 else f"p{pages[0]}"

    # STEP 1: Build sections_list (all headings with their scopes)
    heading_indices = [(i, b) for i, b in enumerate(blocks) if b.block_type == "heading"]
    if not heading_indices:
        output_md = f"# {doc_title}\n\n{render(blocks)}"
        fallback_content = f"# {doc_title}\n\n{_page_range(blocks)}\n\n---\n\n{render(blocks)}"
        fallback_meta = [{
            "filename": "sections/001_document.md",
            "title": doc_title,
            "page_start": blocks[0].page_number if blocks else 1,
            "page_end": blocks[-1].page_number if blocks else 1,
            "pages": _page_range(blocks),
            "heading_level": 1,
            "parent_path": "",
            "block_ids": [b.block_id for b in blocks if b.block_type not in _EXCLUDE_TYPES],
            "context_block_ids": {"before": [], "after": []},
        }]
        fallback_content = f"---\ntitle: {doc_title}\npages: {_page_range(blocks)}\nheading_level: 1\n---\n\n{render(blocks)}"
        return {"001_document.md": fallback_content}, fallback_meta, output_md

    # ── Step 1: Assign every block to exactly one file ───────────────────────
    # Scan in order; current_heading is the last H1/H2/H3 seen.
    # H4+ headings fall into the current file's body (not their own file).
    file_sections: list[tuple[Block, list[Block]]] = []
    preamble: list[Block] = []
    current_heading: Block | None = None
    current_body: list[Block] = []

    for block in blocks:
        if block.block_type == "heading" and (block.heading_level or 2) in _SECTION_LEVELS:
            if current_heading is not None:
                file_sections.append((current_heading, current_body))
            else:
                preamble = list(current_body)
            current_heading = block
            current_body = []
            continue
        if current_heading is not None:
            current_body.append(block)
        else:
            current_body.append(block)

    if current_heading is not None:
        file_sections.append((current_heading, current_body))

    if not file_sections:
        # No H1/H2/H3 found at all — treat entire document as one file
        output_md = f"# {doc_title}\n\n{render(blocks)}"
        all_valid = [b for b in blocks if b.block_type not in _EXCLUDE_TYPES]
        fallback_meta = [{
            "filename": "sections/001_document.md",
            "title": doc_title,
            "page_start": blocks[0].page_number if blocks else 1,
            "page_end": blocks[-1].page_number if blocks else 1,
            "pages": _page_range(blocks),
            "heading_level": 1,
            "parent_path": "",
            "block_ids": [b.block_id for b in all_valid],
            "context_block_ids": {"before": [], "after": []},
        }]
        fallback_content = f"---\ntitle: {doc_title}\npages: {_page_range(blocks)}\nheading_level: 1\n---\n\n{render(blocks)}"
        return {"001_document.md": fallback_content}, fallback_meta, output_md

    # Prepend preamble blocks to first file
    if preamble:
        first_h, first_body = file_sections[0]
        file_sections[0] = (first_h, preamble + first_body)

    # ── Step 2: Build parent chain for each section using a level stack ──────
    level_stack: dict[int, str] = {}  # level → heading title
    section_parents: list[list[str]] = []
    for heading, _ in file_sections:
        level = heading.heading_level or 2
        for l in [k for k in level_stack if k >= level]:
            del level_stack[l]
        section_parents.append([level_stack[l] for l in sorted(level_stack)])
        level_stack[level] = heading.content.strip()

    # ── Step 3: Precompute block→index map for O(1) context lookups ──────────
    block_idx: dict[str, int] = {b.block_id: i for i, b in enumerate(blocks)}

    # ── Step 4: Generate files and manifest entries ───────────────────────────
    sections: dict[str, str] = {}
    sections_meta: list[dict] = []
    used_fnames: set[str] = set()

    for file_num, ((heading, body_blocks), parent_titles) in enumerate(
        zip(file_sections, section_parents), start=1
    ):
        level = heading.heading_level or 2
        parent_path = " > ".join(parent_titles)

        # Filename: immediate-parent prefix + leaf slug
        leaf_slug = _slug(heading.content.strip())
        base = (f"{file_num:03d}_{_slug(parent_titles[-1])}__{leaf_slug}"
                if parent_titles else f"{file_num:03d}_{leaf_slug}")
        fname = (base[:117] + ".md") if len(base) > 117 else (base + ".md")
        stem, ext = fname.rsplit(".", 1)
        n = 1
        while fname in used_fnames:
            fname = f"{stem}_{n}.{ext}"
            n += 1
        used_fnames.add(fname)

        # Renderable body (exclude invalid-page and failure blocks)
        renderable = [b for b in body_blocks if b.block_type not in _EXCLUDE_TYPES]
        all_file_blocks = [heading] + renderable
        page_range = _page_range(all_file_blocks)
        pages = sorted({b.page_number for b in all_file_blocks if b.page_number > 0})

        # Context block IDs for manifest
        h_pos = block_idx.get(heading.block_id, 0)
        scope_end = max(
            (block_idx[b.block_id] + 1 for b in body_blocks if b.block_id in block_idx),
            default=h_pos + 1,
        )
        ctx_before, ctx_after = _get_context_blocks(blocks, h_pos, scope_end, context_pages)

        # YAML frontmatter
        title_str = heading.content.strip()
        fm: dict = {"title": title_str, "heading_level": level, "pages": page_range}
        if parent_path:
            fm["parent_path"] = parent_path
        fm_lines = ["---"]
        for k, v in fm.items():
            fm_lines.append(f'{k}: "{v}"' if isinstance(v, str) and any(c in v for c in ':#"\'') else f"{k}: {v}")
        fm_lines.extend(["---", ""])

        body_md = render(renderable, initial_heading_level=level) if renderable else ""
        sections[fname] = "\n".join(fm_lines) + ("\n" + body_md if body_md else "")

        sections_meta.append({
            "filename": f"sections/{fname}",
            "title": title_str,
            "page_start": pages[0] if pages else 1,
            "page_end": pages[-1] if pages else 1,
            "pages": page_range,
            "heading_level": level,
            "parent_path": parent_path,
            "block_ids": [b.block_id for b in all_file_blocks],
            "context_block_ids": {
                "before": [blocks[i].block_id for i in ctx_before],
                "after":  [blocks[i].block_id for i in ctx_after],
            },
        })

        if verbose:
            indent = "  " * (level - 1)
            print(f"  {indent}{fname}: H{level} '{title_str[:40]}' {page_range}")

    output_md = f"# {doc_title}\n\n{render(blocks)}"
    return sections, sections_meta, output_md
