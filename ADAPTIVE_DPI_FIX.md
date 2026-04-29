# Adaptive DPI Parameter Fix ✅

## Problem
AccidentStatement.pdf was extracting 0 characters despite being a high-resolution scanned document (2896×4096).

**Root Cause:** Fixed DPI=300 parameter was over-zooming high-res scans, rendering them unreadable to OCR.

## Solution
Implemented automatic document type detection in `liteparse_extractor.py`:

```python
def detect_document_type(file_path: Path) -> tuple[str, int]:
    """
    Detect if document is high-res scan or born-digital, return type and adaptive DPI.
    High-res scans (width > 1500 or height > 2000) need lower DPI to avoid over-zoom.
    """
    # Extract page dimensions from PDF
    # High-res scan → DPI 150 (prevents over-zoom)
    # Born-digital → DPI 300 (maximum clarity)
```

## Test Results

### Before Fix
| Document | Type | DPI | Output |
|-----------|------|-----|--------|
| AccidentStatement.pdf | High-res scan | 300 | ❌ 0 chars |

### After Fix
| Document | Type | DPI | Output |
|-----------|------|-----|--------|
| 01_image_across_page_boundary.pdf | born-digital | 300 | ✅ 2.42s |
| 02_table_across_page_boundary.pdf | born-digital | 300 | ✅ 0.39s |
| 03_image_across_chunk_boundary_same_page.pdf | born-digital | 300 | ✅ 4.44s |
| 04_50_page_mixed_boundary_stress.pdf | born-digital | 300 | ✅ 4.35s |
| AccidentStatement.pdf | **high-res-scan** | **150** | ✅ **11,266 chars** |
| Invoice.jpg | unknown | 300 | ✅ 2.05s |
| LabReport.pdf | born-digital | 300 | ✅ 3.34s |
| PerformanceCharts.pdf | born-digital | 300 | ✅ 3.90s |
| salesforce_release_notes_3-25-2026.pdf | born-digital | 300 | ✅ 98.86s |

**Total Time:** ~135 seconds for 9 documents (including 1130-page Salesforce PDF)

## Impact
- ✅ AccidentStatement extraction: **0 → 11,266 characters** (+∞%)
- ✅ Text items: **0 → 563** (+∞%)
- ✅ Bounding boxes: **0 → 563** (+∞%)
- ✅ Maintains high quality for born-digital documents (DPI=300)
- ✅ Automatically handles mixed document types in single batch

## Implementation Details
- Added `PyPDF2` dependency to detect page dimensions
- Detection threshold: width > 1500 or height > 2000 → high-res scan
- Fallback: unknown type → defaults to DPI=300 (born-digital)
- Detection runs per-file, enabling batch processing of mixed types

## Quality Assurance
AccidentStatement JSON output confirms proper extraction:
```json
{
  "page": 1,
  "width": 2896,
  "height": 4096,
  "textItemsCount": 563,
  "boundingBoxCount": 563
}
```

All text items have coordinates (precise_bounding_box=True), enabling layout reconstruction and post-processing.

## Files Modified
- `liteparse_extractor.py`: Added `detect_document_type()` function, integrated adaptive DPI selection
- `requirements.txt`: Added `PyPDF2` dependency
