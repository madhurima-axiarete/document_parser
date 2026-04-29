# Troubleshooting Production Pipeline

## Cost Estimation

The pipeline now shows **estimated cost before processing**:

```python
result = run('test_docs/SalesforceFile.pdf')
# Output includes:
#   cost_estimate: {
#       'input_tokens': 500000,
#       'output_tokens': 96000,
#       'input_cost': 1.50,
#       'output_cost': 1.44,
#       'total_cost': 2.94,
#       'cost_per_page': 0.0026
#   }
```

**Pricing (Claude Sonnet 4.6):**
- Input: $3.00 per 1M tokens
- Output: $15.00 per 1M tokens

**Cost by document type:**
| Document | Pages | Est. Input Tokens | Est. Output Tokens | Est. Cost |
|----------|-------|------|------|------|
| LabReport.pdf | 2 | 3,000 | 8,000 | $0.13 |
| AccidentStatement.pdf | 1 | 2,500 | 4,000 | $0.07 |
| Invoice.jpg | 1 | 3,000 | 2,000 | $0.03 |
| SalesforceFile.pdf | 1,130 | 750,000 | 96,000 | $2.50 |

## Salesforce PDF Chunk Failures

The Salesforce PDF (43MB, 1130 pages) chunks into 24 chunks, but many are failing with **JSON parse errors**.

### Why This Happens

When processing very large documents with many consecutive API calls, several issues can occur:

1. **Rate Limiting** — Anthropic API may throttle requests if too many are sent rapidly
2. **Content Issues** — Some pages may contain problematic content that confuses the extractor
3. **JSON Parsing** — Claude's response isn't valid JSON (structural issue or model failure)
4. **Token Limits** — Pages with extremely dense content may exceed output budget

### Debugging Failed Chunks

Check what went wrong:

```python
import json

# Look at the profile
profile = json.loads(open('output/production_pipeline/salesforce_release_notes_3-25-2026/profiles/doc_profile.json').read())
print(f"Total pages: {profile['total_pages']}")
print(f"Scanned pages: {profile['scanned_page_count']}")
print(f"Image-heavy pages: {profile['image_heavy_page_count']}")
print(f"Avg tokens/page: {profile['avg_input_tokens_per_page']:.0f}")

# Look at chunk plans
chunk_plans = json.loads(open('output/production_pipeline/salesforce_release_notes_3-25-2026/profiles/chunk_plans.json').read())
for i, cp in enumerate(chunk_plans[:5]):
    print(f"Chunk {i}: pages {cp['target_pages'][0]}-{cp['target_pages'][-1]}, "
          f"estimated tokens: {cp['estimated_input_tokens']}")
```

### Solution: Retry with Backoff

The pipeline now includes **exponential backoff** for retries:
- Attempt 1: Immediate
- Attempt 2: Wait 2 seconds
- Attempt 3: Wait 4 seconds
- Attempt 4: Wait 8 seconds

Enable verbose mode to see retries:

```bash
python3 -c "
from production_pipeline import run
result = run('test_docs/salesforce_release_notes_3-25-2026.pdf', verbose=True)
print(f'Success: {result[\"markdown_path\"] is not None}')
print(f'Warnings: {len(result[\"warnings\"])}')
"
```

### Solution: Reduce Chunk Size

If retries don't work, edit `production_pipeline/chunker.py`:

```python
_TOKEN_BUDGET = 30_000  # Reduce from 36_000 to 30_000
_MAX_CHUNK_PAGES = 40   # Reduce from 50 to 40
```

This creates more, smaller chunks that are less likely to fail.

### Solution: Re-run Individual Chunks

After a partial failure, re-run specific chunks:

```python
from production_pipeline import rerun_chunk

# Re-run chunk 5 (pages 201-250)
result = rerun_chunk(
    'test_docs/salesforce_release_notes_3-25-2026.pdf',
    chunk_index=5
)

print(f"Re-extracted: {result['blocks_extracted']} blocks")
```

The pipeline will splice the new results back into `raw_blocks.json` and re-render the Markdown.

## Common Errors

### "anthropic package not installed"
```bash
pip install anthropic>=0.40.0
```

### "PyMuPDF not installed"
```bash
python3 -m pip install --break-system-packages PyMuPDF
```

### "ANTHROPIC_API_KEY not set"
```bash
export ANTHROPIC_API_KEY='sk-...'
```

### "Failed to parse JSON response"

This means Claude returned something that isn't valid JSON. Causes:
1. **Rate limit hit** — Anthropic returned an error response
2. **Model response format** — Claude didn't return JSON (e.g., returned Markdown or error text)
3. **Token timeout** — Response was cut off mid-JSON

**Fix:** 
- Increase retry count: `run(..., max_retries=3)`
- Reduce chunk size (fewer pages per chunk)
- Check verbose output to see what Claude returned

### "No content to extract"

Pages had no text or images. This is rare but can happen with:
- Blank pages
- Pages with only watermarks
- Corrupted PDF pages

## Performance Tips

### For Large Documents (100+ pages)

1. **Process in stages**: Extract chunks separately, combine results
```bash
# Just first 10 chunks
python3 -c "
from production_pipeline import pipeline
doc, size = pipeline.normalizer.normalize('test_docs/large.pdf')
profile = pipeline.profiler.profile_document(doc, 'large.pdf', size)
chunks = pipeline.chunker.plan_chunks(profile)
# Process chunks[0:10] separately
"
```

2. **Use smaller chunks**:
```python
from production_pipeline import chunker
chunker._TOKEN_BUDGET = 20_000  # 20K instead of 36K
```

3. **Run overnight**: Large documents can take hours
```bash
nohup python3 run_production_pipeline.py > batch.log 2>&1 &
tail -f batch.log
```

### For Cost Optimization

1. **Use claude_smart for PDFs only** — costs 30% less
2. **Merge adjacent pages** — fewer API calls
3. **Batch similar-sized documents** — amortize startup overhead
4. **Process during low-demand hours** — no rate limiting

## Getting Help

Include in your bug report:
1. Document filename and size
2. Chunk number that failed
3. Verbose output (last 50 lines)
4. Token counts from `doc_profile.json`
5. Full error message from `output/*/raw_blocks.json`
