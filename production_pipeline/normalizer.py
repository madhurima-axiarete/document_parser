from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Optional


def _sniff_image_media_type(blob: bytes) -> str:
    if blob[:2] == b"\xff\xd8":
        return "image/jpeg"
    if blob[:4] == b"\x89PNG":
        return "image/png"
    if blob[:4] in (b"GIF8", b"GIF9"):
        return "image/gif"
    return "image/png"


def _html_to_pdf_bytes(html: str) -> bytes:
    import fitz

    story = fitz.Story(html)
    mediabox = fitz.paper_rect("a4")
    where = mediabox + (50, 50, -50, -50)

    buf = io.BytesIO()
    writer = fitz.DocumentWriter(buf)
    more = True
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    return buf.getvalue()


def _docx_to_html(content: bytes) -> str:
    from docx import Document
    from docx.oxml.ns import qn

    doc = Document(io.BytesIO(content))

    img_map: dict[str, str] = {}
    for rId, rel in doc.part.rels.items():
        if "image" in rel.reltype:
            blob = rel.target_part.blob
            mt = _sniff_image_media_type(blob)
            img_map[rId] = f"data:{mt};base64,{base64.b64encode(blob).decode()}"

    parts = ["<html><body>"]

    for block in doc.element.body:
        tag = block.tag.split("}")[-1]

        if tag == "p":
            style = getattr(getattr(block, "style", None), "name", "") or ""
            text = block.text.strip() if hasattr(block, "text") else ""

            if not text:
                parts.append("<br/>")
                continue

            if "Heading 1" in style:
                parts.append(f"<h1>{text}</h1>")
            elif "Heading 2" in style:
                parts.append(f"<h2>{text}</h2>")
            elif "Heading 3" in style:
                parts.append(f"<h3>{text}</h3>")
            elif "List" in style:
                parts.append(f"<li>{text}</li>")
            else:
                parts.append(f"<p>{text}</p>")

            for blip in block.iter(qn("a:blip")):
                embed = blip.get(qn("r:embed"))
                if embed and embed in img_map:
                    parts.append(f'<img src="{img_map[embed]}" style="max-width:100%;"/>')

        elif tag == "tbl":
            parts.append("<table border='1' cellpadding='4'>")
            for row in block:
                if row.tag.split("}")[-1] != "tr":
                    continue
                parts.append("<tr>")
                for cell in row:
                    if cell.tag.split("}")[-1] != "tc":
                        continue
                    cell_text = "".join(
                        p.text or ""
                        for p in cell.iter()
                        if p.tag.endswith("}t")
                    )
                    parts.append(f"<td>{cell_text}</td>")
                parts.append("</tr>")
            parts.append("</table>")

    parts.append("</body></html>")
    return "\n".join(parts)


def _pptx_to_html(content: bytes) -> str:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    prs = Presentation(io.BytesIO(content))
    parts = ["<html><body>"]

    for slide_num, slide in enumerate(prs.slides, start=1):
        parts.append(f"<h2>Slide {slide_num}</h2>")

        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    text = para.text.strip() if para.text else ""
                    if text:
                        parts.append(f"<p>{text}</p>")

            if shape.has_table:
                parts.append("<table border='1' cellpadding='4'>")
                for row in shape.table.rows:
                    parts.append("<tr>")
                    for cell in row.cells:
                        parts.append(f"<td>{cell.text.strip()}</td>")
                    parts.append("</tr>")
                parts.append("</table>")

            if shape.has_chart:
                chart = shape.chart
                parts.append("<pre>")
                try:
                    for series in chart.series:
                        vals = list(series.values)
                        parts.append(f"Series '{series.name}': {vals}")
                except Exception:
                    parts.append("[chart — data unavailable]")
                parts.append("</pre>")

            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                try:
                    blob = shape.image.blob
                    mt = _sniff_image_media_type(blob)
                    b64 = base64.b64encode(blob).decode()
                    parts.append(f'<img src="data:{mt};base64,{b64}" style="max-width:100%;"/>')
                except Exception:
                    pass

        parts.append("<hr/>")

    parts.append("</body></html>")
    return "\n".join(parts)


def _xlsx_to_html(content: bytes) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    parts = ["<html><body>"]
    for name in wb.sheetnames:
        ws = wb[name]
        parts.append(f"<h2>{name}</h2><table border='1' cellpadding='4'>")
        for row in ws.iter_rows(values_only=True):
            parts.append("<tr>" + "".join(f"<td>{v or ''}</td>" for v in row) + "</tr>")
        parts.append("</table>")
    parts.append("</body></html>")
    return "\n".join(parts)


_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_TEXT_EXTS = {".txt", ".md", ".csv", ".html", ".htm", ".json", ".xml", ".yaml", ".yml"}


def normalize(file_path: str | Path) -> tuple:
    """
    Normalize any supported file format to a fitz.Document.
    Returns (fitz_doc, file_size_bytes).

    Caller is responsible for calling doc.close() when done.
    """
    import fitz

    path = Path(file_path)
    ext = path.suffix.lower()
    content = path.read_bytes()
    file_size = len(content)

    if ext == ".pdf":
        doc = fitz.open(stream=content, filetype="pdf")
    elif ext in {".docx", ".pptx"}:
        doc = fitz.open(path)
        try:
            pdf_bytes = doc.convert_to_pdf()
            doc.close()
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception:
            doc.close()
            raise
    elif ext == ".xlsx":
        html = _xlsx_to_html(content)
        pdf_bytes = _html_to_pdf_bytes(html)
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    elif ext in _IMAGE_EXTS:
        doc = fitz.open(stream=content, filetype=ext[1:])
    elif ext in _TEXT_EXTS:
        try:
            text = content.decode("utf-8", errors="replace")
        except Exception:
            text = str(content)
        html = f"<html><body><pre>{text}</pre></body></html>"
        pdf_bytes = _html_to_pdf_bytes(html)
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    else:
        try:
            text = content.decode("utf-8", errors="replace")
        except Exception:
            text = str(content)
        html = f"<html><body><pre>{text}</pre></body></html>"
        pdf_bytes = _html_to_pdf_bytes(html)
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    return doc, file_size
