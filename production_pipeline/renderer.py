from __future__ import annotations

import json
from .models import Block


def _render_table(content) -> str:
    """Render a table JSON into GFM markdown table format."""
    try:
        if isinstance(content, str):
            rows = json.loads(content)
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
    except (json.JSONDecodeError, TypeError, IndexError, ValueError):
        return ""


def render(blocks: list[Block]) -> str:
    """Convert list of Block objects to final Markdown string.

    Filters out suppressed blocks and applies type-specific rendering.
    """
    output_parts: list[str] = []

    for block in blocks:
        if block.metadata.get("suppress_in_output"):
            continue

        rendered = ""

        if block.block_type == "heading":
            level = block.heading_level or 2
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
            if not block.metadata.get("suppress_in_output"):
                rendered = block.content
        else:
            rendered = block.content

        if rendered:
            output_parts.append(rendered)

    markdown = "\n\n".join(output_parts)
    return markdown
