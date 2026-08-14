# Document Extraction Pipeline

A production-grade document extraction system that intelligently chunks documents, extracts structured content using Claude API, and organizes output for scalable search and retrieval.

## Overview

This system processes PDFs and documents of any size (1 page → 1200+ pages) and extracts structured content with:
- **Intelligent chunking** — Token-budget aware page grouping
- **Boundary reconciliation** — Handles continuations across chunk boundaries
- **Multi-format output** — Consolidated document + per-chapter markdown for scalable search
- **Native PDF structure** — Uses native table of contents for large documents
- **Flexible provider support** — Anthropic, AWS Bedrock, Google Vertex AI

## Quick Start

### Prerequisites
```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY="your-api-key"
```

### Run on Test Documents
```bash
# Process one document
python3 run_prod_pipeline.py --include LabReport -v

# Process all test documents
python3 run_prod_pipeline.py -v

# Skip large documents
python3 run_prod_pipeline.py --exclude-salesforce -v

# List available documents
python3 run_prod_pipeline.py --list test_docs/
```

### Query Extracted Content
```bash
# Search with full-text + Claude answer
python3 query_document.py --doc output/production_pipeline/LabReport/ --query "test results"

# Show specific page
python3 query_document.py --doc output/production_pipeline/LabReport/ --page 2

# Show table of contents
python3 query_document.py --doc output/production_pipeline/LabReport/ --toc

# List all processed documents
python3 query_document.py --list output/production_pipeline/
```

## Architecture

### Pipeline Strategy

The system uses a **token-budget chunking strategy**:

1. **Profiling** — Analyze document:
   - Extract pages, estimated tokens per page
   - Detect scanned content, images, tables
   - Extract native PDF table of contents
   
2. **Chunking** — Group pages into extraction units:
   - Target ~4000 tokens per chunk (configurable)
   - Respect logical boundaries (don't split mid-table)
   - Track context pages before/after
   
3. **Extraction** — Process chunks in parallel:
   - Claude API extracts text, tables, figures, headings
   - Each block tagged with: type, page, confidence, sequence
   - Retry on failure with exponential backoff
   
4. **Reconciliation** — Handle chunk boundaries:
   - Merge text continuations (is_continuation flag)
   - Detect near-duplicates, repeated headers/footers
   - Annotate instead of deleting (preserves data integrity)
   - Optional LLM arbitration for ambiguous cases
   
5. **Rendering** — Create output files:
   - **output.md** — Consolidated document (for search)
   - **index.md** — Table of contents with native PDF structure
   - **chapters/chapter_*.md** — Individual chapters (for navigation)
   - **raw_blocks.json** — Structured block data (for programmatic access)
   
6. **Storage** — Save all outputs to `output/production_pipeline/{document}/`

### Data Model

**Block** — Atomic unit of extracted content
```python
Block(
    block_id: str,              # Unique identifier
    block_type: str,            # paragraph|heading|table|figure|list_item|code|header|footer
    content: str,               # Text or JSON (for tables)
    page_number: int,           # 1-indexed
    chunk_id: str,              # Which extraction chunk
    sequence: int,              # Global order
    confidence: float,          # Extraction confidence 0-1
    heading_level: int | None,  # 1-6 for headings
    is_truncated: bool,         # Content was cut off
    is_continuation: bool,      # Continues from previous block
    metadata: dict,             # Flags, annotations
)
```

**DocProfile** — Document-level metrics
```python
DocProfile(
    total_pages: int,
    avg_text_chars_per_page: float,
    avg_input_tokens_per_page: float,
    scanned_page_count: int,           # OCR'd pages
    image_heavy_page_count: int,
    table_heavy_page_count: int,
    toc: list[Chapter],                # Native PDF table of contents
    page_profiles: list[PageProfile],   # Per-page analysis
)
```

## Output Structure

```
output/production_pipeline/{document}/
├── output.md                    # Consolidated document
│                               #  - Full text for full-document search
│                               #  - Uses render() for proper structure
│                               #  - Handles continuations, tables, figures
│                               #  - One file with all content
│
├── index.md                     # Table of Contents
│                               #  - Native PDF TOC (if available)
│                               #  - Chapter index with relative links
│                               #  - Works in S3, local, any storage
│
├── chapters/
│   ├── chapter_000.md          # Individual chapters
│   └── chapter_NNN.md          #  - Memory-efficient on-demand reading
│                               #  - Better for version control
│                               #  - Navigate via index.md
│
├── raw_blocks.json              # Structured data (authoritative)
│                               #  - All reconciled blocks
│                               #  - Use for programmatic queries
│                               #  - query_document.py uses this
│
└── profiles/
    └── doc_profile.json        # Document metrics + native TOC
```

## Scalability

### For Small Documents (1-50 pages)
- Single chunk extraction
- output.md ≈ chapter_000.md (identical)
- index.md shows simple structure
- Backward compatible behavior

### For Large Documents (100+ pages)
- Multiple chunks extracted in parallel
- **output.md** — Search full document efficiently
- **index.md** — Navigate by native TOC
- **chapters/** — Read specific sections only
- Memory efficient: don't load whole document

### For Very Large Documents (1000+ pages)
- Native PDF TOC drives chapter boundaries
- Stream rendering (write per-chapter)
- Chapter files ≤ 100KB (manageable size)
- Supports S3/cloud storage with relative links

## Search Workflow

### Use Case: Find "test results" in a 100-page document

```bash
# 1. Full-text search in consolidated document
grep "test results" output/production_pipeline/report/output.md
# → Found at line 256

# 2. Navigate using index
cat output/production_pipeline/report/index.md
# → "test results" appears in Chapter 3 (pages 45-67)

# 3. Read specific chapter
cat output/production_pipeline/report/chapters/chapter_003.md

# 4. Or use structured query
python3 query_document.py --doc output/production_pipeline/report/ \
  --query "test results"
# → Smart search on raw_blocks.json + Claude answer
```

## Configuration

### Chunking Strategy (`production_pipeline/chunker.py`)
- `TARGET_CHUNK_TOKENS = 4000` — Max tokens per extraction
- Adjustable based on API limits and latency

### Boundary Reconciliation (`production_pipeline/boundary.py`)
- Detects: continuations, duplicates, headers/footers
- Annotates with metadata instead of deleting
- Optional LLM arbitration for ambiguous cases

### Extraction Models
```bash
# Anthropic (default)
python3 run_prod_pipeline.py --provider anthropic

# AWS Bedrock
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."
export AWS_DEFAULT_REGION="us-west-2"
python3 run_prod_pipeline.py --provider bedrock

# Google Vertex AI
export VERTEX_PROJECT_ID="..."
export VERTEX_REGION="us-central1"
python3 run_prod_pipeline.py --provider vertex
```

## Cost & Performance

### Token Estimates
- Full-text pages: ~250 tokens per page
- Scanned/image-heavy: varies (up to 1000+ per page)
- Tables, figures: variable based on complexity

### Pipeline Performance
- 2-page document: ~30-40s (1 chunk)
- 100-page document: ~2-3 min (3-4 chunks in parallel)
- Cost scaling: Linear with content volume

### Optimization Tips
1. **Smaller chunks** → Lower cost, more parallelism, slower per-chunk
2. **Larger chunks** → Higher cost, less parallelism, faster per-chunk
3. **Batch processing** → Cooldown between documents (rate limiting)

## Data Integrity

### No Data Deletion
- Repeated headers/footers: **Annotated** (not removed)
- Near-duplicates: **Marked** (not removed)
- Continuations: **Flagged** (not split)
- All information preserved in `metadata` field

### Reconciliation Strategy
- Deterministic rules handle 95% of boundaries
- LLM arbitration for ambiguous cases
- All decisions logged in doc_profile

## Development

### Key Modules
- `production_pipeline/normalizer.py` — Load PDFs
- `production_pipeline/profiler.py` — Analyze documents, extract TOC
- `production_pipeline/chunker.py` — Create extraction strategy
- `production_pipeline/extractor.py` — Call Claude API
- `production_pipeline/boundary.py` — Reconcile chunk boundaries
- `production_pipeline/renderer.py` — Format output (markdown)
- `production_pipeline/storage.py` — Save files
- `production_pipeline/models.py` — Data structures
- `production_pipeline/costs.py` — Token/cost estimation

### Adding New Block Types
1. Update `Block.block_type` in extraction prompt
2. Add rendering logic in `renderer.py`
3. Update `boundary.py` if boundary-specific handling needed

## Troubleshooting

### "JSON parse error on chunk N"
- Chunk too large for model output
- Pipeline halves chunk and retries
- If persists, check API rate limits

### "File not found: test_docs/..."
- Use `python3 run_prod_pipeline.py --list` to see available docs
- Files in `test_docs/` must be PDF or JPG

### Missing output files
- Check `profiles/doc_profile.json` for extraction errors
- Review console output for warnings
- Ensure sufficient disk space in `output/`

### Search returning no results
- Use `--toc` flag to verify document structure
- Check `raw_blocks.json` exists
- Verify query keywords match extracted text

## Future Enhancements

- [ ] SQLite FTS5 for very large documents (optional)
- [ ] Streaming output for gigabyte-scale documents
- [ ] Multi-language support
- [ ] Custom extraction prompts per document type
- [ ] Post-processing hooks for domain-specific cleanup

## License & Attribution

Uses Claude API via Anthropic SDK. Supports multiple AI providers (Bedrock, Vertex).

---

**Questions?** Check `production_pipeline/` module docstrings or run with `--help` flag.
