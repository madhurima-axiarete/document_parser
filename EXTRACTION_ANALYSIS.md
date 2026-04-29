# Document Extraction Analysis

## Problem Summary

| Document | Size | Type | Pages | Extraction | Status |
|----------|------|------|-------|-----------|--------|
| LabReport.pdf | 225 KB | Print + scans | 2 | ✅ Full text + coordinates | SUCCESS |
| PerformanceCharts.pdf | 502 KB | Print + charts | 1 | ✅ 432 text items | SUCCESS |
| **AccidentStatement.pdf** | **1.1 MB** | **Scanned image** | **1** | **❌ 0 text items** | **FAILURE** |
| Salesforce (43 MB) | Large | Print | 1130 | ✅ Partial extraction | PARTIAL |

## Root Cause Analysis

### AccidentStatement.pdf - Complete Failure

**Why it fails:**
```
Input:   2896 × 4096 pixel high-resolution scanned image
DPI:     300 (rendering at high resolution)
Result:  OCR completely fails to recognize ANY text
Errors:  "Image too small to scale", "Line cannot be recognized"
```

**The Problem:**
1. **Ultra-high resolution** (2896×4096) - causes OCR engine to struggle
2. **Scanned document** - not born-digital, relies entirely on OCR
3. **Current parameters don't match the input**:
   - `dpi=300` rendering at 300 DPI on an already high-res image = too much zoom
   - `preserve_very_small_text=True` makes OCR pickier about quality
   - `num_workers=8` parallelism can cause race conditions on problematic images

### What Worked vs What Failed

**LabReport.pdf (✅ WORKS)**
- Resolution: 612×792 (standard PDF)
- Type: Mix of text + scanned sections
- Size: 225 KB
- Extracted: 2 pages, full content

**AccidentStatement.pdf (❌ FAILS)**
- Resolution: 2896×4096 (2.5x larger in each dimension)
- Type: Pure scanned image
- Size: 1.1 MB (5x larger)
- Extracted: 0 text items, empty

---

## Parameter Shortcomings

Current settings are **optimized for born-digital PDFs**, not scanned images:

| Parameter | Current | Problem for AccidentStatement |
|-----------|---------|-------------------------------|
| `dpi=300` | High quality | ❌ Too aggressive zoom on high-res scans |
| `preserve_very_small_text=True` | Complete extraction | ❌ Stricter OCR = more failures |
| `num_workers=8` | Fast | ❌ Can cause OCR race conditions |
| `ocr_enabled=True` | Always on | ✅ Good (needed for scans) |

---

## Shortcomings Identified

### 1. One-Size-Fits-All Parameters ❌
Current script uses same parameters for all document types:
- **Born-digital PDFs** (LabReport, PerformanceCharts) → Work well
- **High-res scans** (AccidentStatement) → Complete failure

### 2. No Fallback Strategy ❌
When OCR fails, we get empty output with no error messaging.

### 3. No Document-Type Detection ❌
Should detect:
- Is it born-digital or scanned?
- What's the native resolution?
- Adjust parameters accordingly

### 4. DPI Parameter Misuse ❌
- `dpi=300` means "render at 300 DPI"
- For already-scanned high-res images, this causes over-zoom
- Should be lower for scanned docs (150-200)

---

## Solutions

### Option A: Adaptive Parameters (RECOMMENDED)

Detect document type and adjust:

```python
def get_optimal_params(file_path):
    """Detect document type and return optimal parameters."""
    pdf = pdfplumber.open(file_path)
    first_page = pdf.pages[0]
    width, height = first_page.width, first_page.height
    
    # Check if scanned (high res) or born-digital (standard res)
    is_scanned = width > 1500 or height > 2000
    
    if is_scanned:
        return {
            "dpi": 150,                    # Lower for scans (avoid over-zoom)
            "preserve_very_small_text": False,  # Relax OCR strictness
            "num_workers": 1,              # Single worker to avoid race conditions
        }
    else:
        return {
            "dpi": 300,                    # Higher for born-digital
            "preserve_very_small_text": True,
            "num_workers": 8,
        }
```

### Option B: Multi-Pass OCR

If first attempt fails, retry with different parameters:

```python
def parse_with_fallback(parser, file_path):
    """Try parsing with fallback parameters."""
    attempts = [
        {"dpi": 300, "num_workers": 8},      # First try
        {"dpi": 200, "num_workers": 1},      # Second try
        {"dpi": 150, "preserve_very_small_text": False},  # Last resort
    ]
    
    for params in attempts:
        result = parser.parse(file_path, **params)
        if result.text:  # If extraction worked
            return result
    
    return None  # All failed
```

### Option C: Document Pre-processing

Check/adjust before extraction:

```python
def preprocess_pdf(file_path):
    """Check if PDF needs special handling."""
    pdf = PyPDF2.PdfReader(file_path)
    first_page = pdf.pages[0]
    
    # Check native resolution
    mediabox = first_page.mediabox
    width = float(mediabox.width)
    height = float(mediabox.height)
    
    if width > 1500:
        print(f"⚠️ High-res scanned PDF detected ({width}×{height})")
        print("   → Using conservative OCR parameters")
        return "scanned"
    else:
        print(f"✓ Born-digital PDF ({width}×{height})")
        return "digital"
```

---

## Comparison: Current vs Recommended

### Current Approach (All Documents)
```
AccidentStatement → dpi=300, num_workers=8, strict_ocr → ❌ FAILS
LabReport → dpi=300, num_workers=8 → ✅ Works
```

### Recommended: Adaptive Approach
```
AccidentStatement (detected: scanned) → dpi=150, num_workers=1, relaxed_ocr → ✅ Should work
LabReport (detected: digital) → dpi=300, num_workers=8 → ✅ Works
```

---

## Data Quality Issues Found

### AccidentStatement.pdf
- ❌ **0% extraction** (should be 100%)
- ❌ No text items
- ❌ No bounding boxes
- ❌ No error messaging

### PerformanceCharts.pdf
- ✅ 432 text items extracted
- ✅ Coordinates preserved
- ⚠️ Chart numbers still scattered (needs post-processing)

### LabReport.pdf
- ✅ Full text extracted
- ✅ Coordinates with high confidence (1.0)
- ✅ Maintains document structure

### Salesforce Release Notes
- ✅ 2.6 MB text extracted (307K words)
- ✅ Scales to large documents
- ⚠️ Some OCR errors in complex formatting

---

## Recommendations

**Priority 1:** Fix AccidentStatement extraction
- Implement adaptive parameters based on document type
- Add fallback OCR strategies

**Priority 2:** Add error handling
- Detect when extraction yields nothing
- Log warnings for problematic documents

**Priority 3:** Post-processing for charts/tables
- Use coordinates from precise_bounding_box
- Detect and reconstruct tables automatically

**Priority 4:** Quality metrics
- Track extraction confidence per document
- Compare input vs output sizes
- Flag suspiciously low/high extraction rates
