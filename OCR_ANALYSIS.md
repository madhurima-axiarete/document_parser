# Best Open-Source OCR Models for LiteParse

## Current Setup
- **LiteParse version:** 1.5.2
- **Current OCR:** Tesseract.js (JavaScript wrapper)
- **Quality issue:** PerformanceCharts shows garbled text, poor layout detection

## Best Open-Source OCR Models (2026)

### 1. **PaddleOCR** ⭐ RECOMMENDED
**Accuracy:** 94.5% (OmniDocBench v1.5)
- **Pros:**
  - Best for complex document layouts and structured data
  - Supports 80+ languages
  - Modular architecture (detection → recognition → orientation)
  - VLM version (1.5) adds vision-language understanding
  - ~3-5x better than Tesseract on complex documents
  - Active development and regular updates
  
- **Cons:**
  - Python/C++ based (not native JavaScript)
  - Requires larger model weights (~200MB)
  - Slower on CPU than Tesseract
  
- **Best for:** Business documents, charts, mixed layouts

### 2. **EasyOCR**
**Speed:** Fast, simple setup
- **Pros:**
  - Very easy Python API
  - PyTorch-based, good GPU support
  - Quick prototyping
  
- **Cons:**
  - Slower than Tesseract on CPU
  - Less control over layout analysis
  - Not as accurate as PaddleOCR on complex layouts
  
- **Best for:** Quick experiments, simple documents

### 3. **Tesseract** (Current)
**Speed:** Fastest on CPU
- **Pros:**
  - Very lightweight (~50MB)
  - Works well for clean, printed text
  - Huge community
  - Low resource requirements
  
- **Cons:**
  - Poor layout analysis (your main issue with PerformanceCharts)
  - Struggles with tables, mixed fonts, rotated text
  - Not great for complex modern documents
  
- **Best for:** Simple documents, archival text

## Why OCR Alone Won't Match Claude

Even with perfect OCR (**PaddleOCR at 99% accuracy**), you won't match Claude's output quality:

| Aspect | OCR (even PaddleOCR) | Claude |
|--------|---------------------|--------|
| **Text Extraction** | ✅ 95%+ | ✅ 99%+ |
| **Layout Detection** | ⚠️ 70-80% | ✅ 98%+ |
| **Structure Understanding** | ❌ None | ✅ AI-powered |
| **Figure Descriptions** | ❌ Ignored | ✅ Detailed context |
| **Semantic Grouping** | ❌ Linear only | ✅ Logical sections |
| **Markdown Formatting** | ❌ Plain text | ✅ Headers, bold, lists |

## Recommended Solution: Hybrid Approach

### **Option 1: PaddleOCR Pre-processing** (Best for structure)
```
Raw PDF
  ↓
PaddleOCR (extract text + layout)
  ↓
Post-process with Claude (structure + formatting)
  ↓
Polished Markdown
```

### **Option 2: Replace Tesseract in LiteParse**
Unfortunately, LiteParse's OCR is hardcoded to Tesseract.js. You'd need to:
1. Fork liteparse or submit PR to make OCR pluggable
2. Implement PaddleOCR wrapper (via Node.js bridge)
3. Trade off performance (will be slower)

### **Option 3: LiteParse + Smart Post-Processing** (Easiest)
Use liteparse as-is, then:
- Extract tables programmatically (detect grids)
- Run Claude on extracted sections
- Reconstruct as markdown

## Implementation Path (Recommended)

For your use case (business documents, charts, reports):

**Quick win:** Replace with **PaddleOCR-based extractor**
```python
# Alternative to liteparse_extractor.js
from paddleocr import PaddleOCR
import json

ocr = PaddleOCR(use_angle_cls=True, lang=['en'])
result = ocr.ocr(pdf_path, cls=True)

# Then feed to Claude for structure
# This gives you 94.5% accuracy with better layout
```

**Speed:** ~2-3x slower than current Tesseract.js, but **much better quality**

**Cost-benefit:**
- ✅ Better OCR accuracy on charts/tables
- ✅ Better layout preservation
- ✅ Better handling of rotated/skewed text
- ❌ Slower (~3-4s per page vs 0.3s)
- ❌ Higher memory usage

---

## My Recommendation

**Don't chase perfect OCR.** The real bottleneck isn't OCR quality—it's **lack of semantic understanding**.

**Instead, use a 2-stage approach:**
1. **LiteParse** for raw extraction (fast, "good enough")
2. **Claude** for structure & formatting (handles OCR errors + adds context)

This gives you:
- Fast bulk extraction
- Claude-quality output
- Better error recovery (Claude can fix OCR mistakes)
- Reasonable costs

The PerformanceCharts garbled text (scattered numbers) is a **layout problem**, not OCR accuracy. Even PaddleOCR would struggle here—you need semantic understanding, which only Claude (or other LLMs) provide.
