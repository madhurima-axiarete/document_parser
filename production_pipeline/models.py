from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Block:
    block_id: str
    block_type: str
    content: str
    page_number: int
    source_file: str
    chunk_id: str
    sequence: int
    confidence: float
    extraction_method: str
    heading_level: Optional[int] = None
    is_truncated: bool = False
    is_continuation: bool = False
    bbox: Optional[tuple[float, float, float, float]] = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "block_id": self.block_id,
            "block_type": self.block_type,
            "content": self.content,
            "page_number": self.page_number,
            "source_file": self.source_file,
            "chunk_id": self.chunk_id,
            "sequence": self.sequence,
            "confidence": self.confidence,
            "extraction_method": self.extraction_method,
            "heading_level": self.heading_level,
            "is_truncated": self.is_truncated,
            "is_continuation": self.is_continuation,
            "bbox": self.bbox,
            "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(d: dict) -> Block:
        return Block(**d)


@dataclass
class PageProfile:
    page_number: int
    text_char_count: int
    image_count: int
    image_area_fraction: float
    table_count: int
    garble_rate: float
    is_scanned: bool
    is_image_heavy: bool
    is_table_heavy: bool
    estimated_input_tokens: int
    page_width_pts: float = 612.0
    page_height_pts: float = 792.0
    max_font_size: float = 12.0
    min_font_size: float = 10.0

    def to_dict(self) -> dict:
        return {
            "page_number": self.page_number,
            "text_char_count": self.text_char_count,
            "image_count": self.image_count,
            "image_area_fraction": self.image_area_fraction,
            "table_count": self.table_count,
            "garble_rate": self.garble_rate,
            "is_scanned": self.is_scanned,
            "is_image_heavy": self.is_image_heavy,
            "is_table_heavy": self.is_table_heavy,
            "estimated_input_tokens": self.estimated_input_tokens,
            "page_width_pts": self.page_width_pts,
            "page_height_pts": self.page_height_pts,
            "max_font_size": self.max_font_size,
            "min_font_size": self.min_font_size,
        }

    @staticmethod
    def from_dict(d: dict) -> PageProfile:
        return PageProfile(**d)


@dataclass
class Chapter:
    """Native PDF table of contents entry."""
    level: int
    title: str
    page_number: int

    def to_dict(self) -> dict:
        return {"level": self.level, "title": self.title, "page_number": self.page_number}

    @staticmethod
    def from_dict(d: dict) -> Chapter:
        return Chapter(**d)


@dataclass
class DocProfile:
    source_file: str
    total_pages: int
    file_size_bytes: int
    avg_text_chars_per_page: float
    avg_input_tokens_per_page: float
    scanned_page_count: int
    image_heavy_page_count: int
    table_heavy_page_count: int
    estimated_total_output_chars: int
    page_profiles: list[PageProfile] = field(default_factory=list)
    toc: list[Chapter] = field(default_factory=list)
    max_font_size_in_doc: float = 12.0
    common_font_sizes: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source_file": self.source_file,
            "total_pages": self.total_pages,
            "file_size_bytes": self.file_size_bytes,
            "avg_text_chars_per_page": self.avg_text_chars_per_page,
            "avg_input_tokens_per_page": self.avg_input_tokens_per_page,
            "scanned_page_count": self.scanned_page_count,
            "image_heavy_page_count": self.image_heavy_page_count,
            "table_heavy_page_count": self.table_heavy_page_count,
            "estimated_total_output_chars": self.estimated_total_output_chars,
            "page_profiles": [p.to_dict() for p in self.page_profiles],
            "toc": [c.to_dict() for c in self.toc],
            "max_font_size_in_doc": self.max_font_size_in_doc,
            "common_font_sizes": self.common_font_sizes,
        }

    @staticmethod
    def from_dict(d: dict) -> DocProfile:
        page_profiles = [PageProfile.from_dict(p) for p in d.pop("page_profiles", [])]
        toc = [Chapter.from_dict(c) for c in d.pop("toc", [])]
        d.setdefault("max_font_size_in_doc", 12.0)
        d.setdefault("common_font_sizes", [])
        doc = DocProfile(**d)
        doc.page_profiles = page_profiles
        doc.toc = toc
        return doc


@dataclass
class ChunkPlan:
    chunk_index: int
    chunk_id: str
    target_pages: list[int]
    context_before: list[int] = field(default_factory=list)
    context_after: list[int] = field(default_factory=list)
    estimated_input_tokens: int = 0
    uses_vision: bool = False
    has_boundary_risk: bool = False

    def to_dict(self) -> dict:
        return {
            "chunk_index": self.chunk_index,
            "chunk_id": self.chunk_id,
            "target_pages": self.target_pages,
            "context_before": self.context_before,
            "context_after": self.context_after,
            "estimated_input_tokens": self.estimated_input_tokens,
            "uses_vision": self.uses_vision,
            "has_boundary_risk": self.has_boundary_risk,
        }

    @staticmethod
    def from_dict(d: dict) -> ChunkPlan:
        return ChunkPlan(**d)


@dataclass
class BoundaryRisk:
    chunk_index: int
    risk_type: str
    last_block_of_chunk: Block
    first_block_of_next_chunk: Block
    resolved: bool = False
    resolution: str = "unresolved"
    llm_decision: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "chunk_index": self.chunk_index,
            "risk_type": self.risk_type,
            "last_block_of_chunk": self.last_block_of_chunk.to_dict(),
            "first_block_of_next_chunk": self.first_block_of_next_chunk.to_dict(),
            "resolved": self.resolved,
            "resolution": self.resolution,
            "llm_decision": self.llm_decision,
        }

    @staticmethod
    def from_dict(d: dict) -> BoundaryRisk:
        last_block = Block.from_dict(d.pop("last_block_of_chunk"))
        first_block = Block.from_dict(d.pop("first_block_of_next_chunk"))
        risk = BoundaryRisk(
            last_block_of_chunk=last_block,
            first_block_of_next_chunk=first_block,
            **d,
        )
        return risk
