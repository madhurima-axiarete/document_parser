# Production Pipeline Usage Guide

## Quick Start

### Process All Test Documents

```bash
python3 run_production_pipeline.py
```

This will:
1. ✓ Find all documents in `test_docs/` (PDF, DOCX, PPTX, XLSX, JPG)
2. ✓ Extract each using the production pipeline
3. ✓ Save results to `output/production_pipeline/{stem}/`
4. ✓ Generate summary table and JSON report

### Process Single Document

```python
from production_pipeline import run

result = run('test_docs/LabReport.pdf', verbose=True)

print(f"Success: {result['markdown_path'] is not None}")
print(f"Chunks: {result['chunk_count']}")
print(f"Time: {result['elapsed_seconds']:.1f}s")
```

### Re-run Single Failed Chunk

```python
from production_pipeline import rerun_chunk

result = rerun_chunk('test_docs/AccidentStatement.pdf', chunk_index=2)
print(f"Re-extracted: {result['blocks_extracted']} blocks")
```

## Output Structure

For each document, the pipeline generates:

```
output/production_pipeline/{stem}/
├── blocks/                    # Per-chunk raw extraction
│   ├── chunk_000.json        # {chunk_id, target_pages, blocks: [...]}
│   ├── chunk_001.json
│   └── ...
├── profiles/
│   ├── doc_profile.json      # Document-level metrics
│   └── chunk_plans.json      # Chunking strategy
├── boundaries/
│   └── boundary_risks.json   # Reconciliation decisions
├── raw_blocks.json           # All blocks post-reconciliation
└── output.md                 # Final Markdown document
```

## Data Structure: Block

Each extracted block contains:

```python
Block(
    block_id: str,              # "{stem}_p{page}_b{seq:04d}"
    block_type: str,            # heading|paragraph|table|figure|header|footer|list_item|code
    content: str,               # text verbatim; tables as JSON array-of-arrays
    page_number: int,           # 1-based
    source_file: str,
    chunk_id: str,
    sequence: int,              # global document order
    confidence: float,          # 1.0=perfect, <1.0=vision extraction
    extraction_method: str,     # "native" or "vision"
    heading_level: Optional[int],  # 1-6 for headings
    is_truncated: bool,         # block cut off at chunk end
    is_continuation: bool,      # block begins mid-content
    metadata: dict,             # table_rows, indent_level, suppress_in_output, etc.
)
```

## Batch Processing Results

✓ **5/6 test documents processed:**

| Document | Pages | Type | Output | Notes |
|----------|-------|------|--------|-------|
| LabReport.pdf | 2 | PDF (mixed) | 4.1 KB | Medical pathology report |
| AccidentStatement.pdf | 1 | PDF (scanned) | 4.7 KB | Insurance document (vision mode) |
| Invoice.jpg | 1 | Image | 1.2 KB | Scanned invoice (vision mode) |
| PerformanceCharts.pdf | 1 | PDF (charts) | 3.3 KB | BCG sustainability report |
| SampleDocument.docx | 5 | DOCX | 1.7 KB | Multi-format test doc |
| salesforce_release_notes_3-25-2026.pdf | 1130 | PDF (large) | ⏳ | 43MB file, will chunk into ~40 chunks |

## Features

### ✓ Format Support
- **PDF**: Native text extraction, vision mode for scanned pages
- **DOCX/PPTX**: Converted to PDF, preserves layout
- **XLSX**: Converted to HTML → PDF, all sheets as tables
- **Images**: JPG, PNG, GIF, WebP (vision mode)
- **Text**: TXT, MD, CSV, HTML, JSON, XML, YAML

### ✓ Intelligent Chunking
- **Dynamic sizing**: Pages chunked by actual token cost (~36K budget per chunk)
- **Vision awareness**: Scanned pages cost 2.5× more, chunk size adjusts
- **Context overlap**: 1 page before/after included for continuity, stripped from output

### ✓ Block-Level Metadata
- **Page numbers**: Every block knows which page it came from
- **Confidence scores**: 1.0 for native text, <1.0 for vision
- **Truncation flags**: Marks blocks cut off at chunk boundaries
- **Continuation flags**: Marks blocks that begin mid-content

### ✓ Intelligent Boundary Reconciliation
- **Header/footer dedup**: Identical headers on 3+ pages are suppressed
- **Table merging**: Tables spanning chunks are reassembled
- **Overlap removal**: Duplicate content from context pages removed
- **List linking**: Multi-page lists tracked via metadata
- **LLM reconciliation**: For ambiguous boundaries only

### ✓ Deterministic Markdown Rendering
- Tables: GFM pipe tables with headers
- Headings: `#` levels match document hierarchy
- Figures: `> **[Figure]**` blocks with detailed descriptions
- Lists: Indentation preserved
- No random formatting — identical input → identical output

## Token Budget

| Page Type | Tokens/Page | Pages/Chunk |
|-----------|------------|------------|
| Pure text (Salesforce-like) | ~600 | 50+ |
| Mixed text + images | ~1000 | 30-45 |
| Full-page scan | ~1105 | ~32 |
| Single image | ~1105 | 1 |

## Retry & Recovery

If extraction fails for a chunk:

1. **View the failure**: Check `boundaries/boundary_risks.json` for details
2. **Re-run just that chunk**: `rerun_chunk(file, chunk_index=N)`
3. **Inspect raw blocks**: `raw_blocks.json` has all extracted data for debugging
4. **Verify context**: Compare last/first blocks of adjacent chunks

## Performance

- **LabReport (2 pages)**: 32s
- **AccidentStatement (1 scanned)**: 64s
- **SampleDocument (5 pages)**: 32s
- **Cost**: ~$0.10–0.30 per document (Sonnet 4.6 pricing)

## Customization

### Run with custom output directory
```python
result = run('path/to/doc.pdf', output_dir='my_output/')
```

### Disable verbose output
```python
result = run('path/to/doc.pdf', verbose=False)
```

### Set API key explicitly
```python
result = run('path/to/doc.pdf', api_key='sk-...')
```

## Troubleshooting

**"anthropic package not installed"**
```bash
pip install anthropic>=0.40.0
```

**"PyMuPDF not installed"**
```bash
pip install --break-system-packages PyMuPDF
```

**"ANTHROPIC_API_KEY not set"**
```bash
export ANTHROPIC_API_KEY='your-key-here'
```

**Large PDF hits token limit**
- Salesforce PDF (43MB, 1130 pages) will chunk into ~40 chunks
- Each chunk costs ~$0.02–0.05 depending on scanned vs. native pages
- Total: ~$1–2 for full extraction

## Files

- `run_production_pipeline.py` — Batch runner for all test_docs
- `production_pipeline/` — Main module (9 files)
- `output/production_pipeline/` — Results directory
