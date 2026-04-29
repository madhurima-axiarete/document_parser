"""
llamaparse_extractor.py

Extracts content from documents using LlamaParse (LlamaIndex agentic parser).

Supports client-side partitioning for large PDFs (>1000 pages).

Requires: LLAMAPARSER_API_KEY env var.
"""

from __future__ import annotations

import asyncio
import io
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

METHOD = "llamaparse"

LLAMAPARSE_API_KEY = os.getenv("LLAMAPARSER_API_KEY")
PARTITION_PAGE_LIMIT = 1000


def _get_pdf_page_count(file_path: Path) -> int:
    """Return page count for a PDF file."""
    if file_path.suffix.lower() != ".pdf":
        return 1
    try:
        from pdfminer.pdfpage import PDFPage

        with open(file_path, "rb") as f:
            return sum(1 for _ in PDFPage.get_pages(f, check_extractable=False))
    except Exception:
        return 0


def _split_pdf_into_chunks(file_path: Path, chunk_size: int = PARTITION_PAGE_LIMIT) -> list[tuple[Path, int, int]]:
    """
    Split a PDF into chunks of at most chunk_size pages.
    Returns list of (temp_file_path, start_page, end_page) tuples.
    """
    import pypdf
    import tempfile

    page_count = _get_pdf_page_count(file_path)
    if page_count <= chunk_size:
        return [(file_path, 0, page_count - 1)]

    chunks = []
    reader = pypdf.PdfReader(str(file_path))

    start_page = 0
    while start_page < len(reader.pages):
        end_page = min(start_page + chunk_size - 1, len(reader.pages) - 1)

        writer = pypdf.PdfWriter()
        for i in range(start_page, end_page + 1):
            writer.add_page(reader.pages[i])

        buf = io.BytesIO()
        writer.write(buf)
        buf.seek(0)

        tmp_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp_file.write(buf.getvalue())
        tmp_file.close()

        chunks.append((Path(tmp_file.name), start_page, end_page))
        start_page = end_page + 1

    return chunks


async def _parse_async(file_path: Path) -> str:
    """Async wrapper around LlamaParse API with automatic chunking for large PDFs."""
    from llama_cloud import AsyncLlamaCloud

    client = AsyncLlamaCloud(api_key=LLAMAPARSE_API_KEY)

    page_count = _get_pdf_page_count(file_path)

    if file_path.suffix.lower() == ".pdf" and page_count > PARTITION_PAGE_LIMIT:
        chunks = _split_pdf_into_chunks(file_path)
        markdown_parts = []

        for chunk_path, start_pg, end_pg in chunks:
            try:
                file_obj = await client.files.create(file=str(chunk_path), purpose="parse")
                result = await client.parsing.parse(
                    file_id=file_obj.id,
                    tier="agentic",
                    version="latest",
                    expand=["markdown_full", "text_full"],
                )
                chunk_md = result.markdown_full or result.text_full or ""
                markdown_parts.append(f"## Pages {start_pg + 1}-{end_pg + 1}\n\n{chunk_md}")
            finally:
                chunk_path.unlink(missing_ok=True)

        return "\n\n---\n\n".join(markdown_parts)
    else:
        file_obj = await client.files.create(file=str(file_path), purpose="parse")
        result = await client.parsing.parse(
            file_id=file_obj.id,
            tier="agentic",
            version="latest",
            expand=["markdown_full", "text_full"],
        )
        return result.markdown_full or result.text_full or ""


def extract(file_path: str) -> dict:
    """Send file to LlamaParse and return the Markdown response."""
    path = Path(file_path)

    if not LLAMAPARSE_API_KEY:
        return {
            "file": path.name,
            "method": METHOD,
            "raw_markdown": "",
            "raw_text_chars": 0,
            "warnings": ["LLAMAPARSER_API_KEY not set — skipping"],
        }

    try:
        raw_markdown = asyncio.run(_parse_async(path))
        return {
            "file": path.name,
            "method": METHOD,
            "raw_markdown": raw_markdown,
            "raw_text_chars": len(raw_markdown),
            "warnings": [],
        }
    except Exception as exc:
        return {
            "file": path.name,
            "method": METHOD,
            "raw_markdown": "",
            "raw_text_chars": 0,
            "warnings": [f"LlamaParse error: {exc}"],
        }
