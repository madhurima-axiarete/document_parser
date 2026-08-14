from __future__ import annotations

import math
import re
from pathlib import Path
from .models import PageProfile, DocProfile, Chapter


_MAX_GARBLE_RATE = 0.05
_MIN_TEXT_LEN = 150


def _extract_font_sizes(page) -> tuple[float, float, list[float]]:
    """Extract font size statistics from page.

    Returns (max_font_size, min_font_size, common_sizes).
    Uses page.get_text("dict") to inspect text span properties.
    """
    font_sizes = []
    try:
        text_dict = page.get_text("dict")
        for block in text_dict.get("blocks", []):
            if block.get("type") == 0:  # Text block
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        size = span.get("size", 0)
                        if size > 0:
                            font_sizes.append(size)
    except Exception:
        pass

    if not font_sizes:
        return 12.0, 10.0, [12.0]

    font_sizes_sorted = sorted(font_sizes)
    max_size = max(font_sizes_sorted)
    min_size = min(font_sizes_sorted)

    # Find common sizes (sizes that appear frequently)
    from collections import Counter
    size_counts = Counter([round(s, 1) for s in font_sizes_sorted])
    common = sorted([size for size, count in size_counts.most_common(3)], reverse=True)

    return max_size, min_size, common if common else [12.0]


def _is_garbled(text: str) -> bool:
    if not text:
        return False
    bad = sum(1 for c in text if c == "�" or (ord(c) < 32 and c not in "\n\r\t"))
    return (bad / len(text)) > _MAX_GARBLE_RATE


def _estimate_vision_tokens(width_pts: float, height_pts: float, dpi: int = 100) -> int:
    """Estimate tokens for a vision page at given DPI.

    Formula: 85 + 170 * ceil(w_px/512) * ceil(h_px/512)
    """
    w_px = width_pts * dpi / 72
    h_px = height_pts * dpi / 72
    tiles_w = math.ceil(w_px / 512)
    tiles_h = math.ceil(h_px / 512)
    return 85 + 170 * tiles_w * tiles_h


def extract_toc(doc) -> list[Chapter]:
    """Extract native PDF table of contents.

    Returns list of Chapter objects from fitz_doc.get_toc().
    """
    try:
        toc = doc.get_toc()
        if not toc:
            return []
        return [Chapter(level=level, title=title, page_number=page) for level, title, page in toc]
    except Exception:
        return []


def profile_page(page, page_number: int) -> PageProfile:
    """Profile a single fitz page.

    Returns PageProfile with all metrics including estimated input tokens.
    """
    try:
        text = page.get_text("text").strip()
        text_char_count = len(text)
    except Exception:
        text = ""
        text_char_count = 0

    image_count = len(page.get_images())
    garble_rate = _is_garbled(text) if text else 0.0
    if garble_rate:
        bad_chars = sum(1 for c in text if c == "�" or (ord(c) < 32 and c not in "\n\r\t"))
        garble_rate = bad_chars / len(text) if text else 0.0

    image_area_fraction = 0.0
    if image_count > 0:
        try:
            page_area = page.rect.width * page.rect.height
            total_img_area = 0.0
            for img_index in page.get_images():
                try:
                    rects = page.get_image_rects(img_index)
                    for rect in rects:
                        total_img_area += rect.width * rect.height
                except Exception:
                    pass
            if page_area > 0:
                image_area_fraction = total_img_area / page_area
        except Exception:
            pass

    table_count = 0
    try:
        tables = page.find_tables().tables
        table_count = len(tables) if tables else 0
    except Exception:
        pass

    is_scanned = text_char_count < _MIN_TEXT_LEN or garble_rate > _MAX_GARBLE_RATE
    is_image_heavy = image_area_fraction > 0.30 or (image_count > 0 and is_scanned)
    is_table_heavy = table_count >= 2

    estimated_input_tokens = _estimate_vision_tokens(page.rect.width, page.rect.height)

    # Extract font statistics for layout-based heading detection
    max_font, min_font, _ = _extract_font_sizes(page)

    return PageProfile(
        page_number=page_number,
        text_char_count=text_char_count,
        image_count=image_count,
        image_area_fraction=image_area_fraction,
        table_count=table_count,
        garble_rate=garble_rate,
        is_scanned=is_scanned,
        is_image_heavy=is_image_heavy,
        is_table_heavy=is_table_heavy,
        estimated_input_tokens=estimated_input_tokens,
        page_width_pts=page.rect.width,
        page_height_pts=page.rect.height,
        max_font_size=max_font,
        min_font_size=min_font,
    )


def profile_document(doc, source_file: str, file_size_bytes: int) -> DocProfile:
    """Profile entire document, returning page-level and document-level metrics.

    Also extracts native PDF table of contents.
    """
    page_profiles: list[PageProfile] = []

    for page_num, page in enumerate(doc, start=1):
        profile = profile_page(page, page_num)
        page_profiles.append(profile)

    total_pages = len(page_profiles)
    scanned_page_count = sum(1 for p in page_profiles if p.is_scanned)
    image_heavy_page_count = sum(1 for p in page_profiles if p.is_image_heavy)
    table_heavy_page_count = sum(1 for p in page_profiles if p.is_table_heavy)

    if total_pages > 0:
        avg_text_chars = sum(p.text_char_count for p in page_profiles) / total_pages
        avg_input_tokens = (
            sum(p.estimated_input_tokens for p in page_profiles) / total_pages
        )
    else:
        avg_text_chars = 0.0
        avg_input_tokens = 0.0

    estimated_total_output_chars = int(avg_text_chars * total_pages * 1.2)

    toc = extract_toc(doc)

    # Compute document-level font statistics for heading detection
    all_font_sizes = []
    for profile in page_profiles:
        all_font_sizes.append(profile.max_font_size)
    max_font_in_doc = max(all_font_sizes) if all_font_sizes else 12.0

    # Find common font sizes across document (heading indicators)
    if page_profiles and len(page_profiles) > 1:
        # Get max sizes from each page and find outliers (likely headings)
        font_maxes = sorted([p.max_font_size for p in page_profiles], reverse=True)
        # Top font sizes that appear in multiple pages
        from collections import Counter
        common_tops = Counter([round(f, 1) for f in font_maxes[:max(1, total_pages // 3)]])
        common_font_sizes = sorted([size for size, _ in common_tops.most_common(2)], reverse=True)
    else:
        common_font_sizes = [max_font_in_doc]

    return DocProfile(
        source_file=source_file,
        total_pages=total_pages,
        file_size_bytes=file_size_bytes,
        avg_text_chars_per_page=avg_text_chars,
        avg_input_tokens_per_page=avg_input_tokens,
        scanned_page_count=scanned_page_count,
        image_heavy_page_count=image_heavy_page_count,
        table_heavy_page_count=table_heavy_page_count,
        estimated_total_output_chars=estimated_total_output_chars,
        page_profiles=page_profiles,
        toc=toc,
        max_font_size_in_doc=max_font_in_doc,
        common_font_sizes=common_font_sizes,
    )
