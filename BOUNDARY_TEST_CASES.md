# Boundary Test Cases for Production Pipeline

These are 4 specially-designed test PDFs to verify the production pipeline handles edge cases correctly.

## Test Documents

### 1. `01_image_across_page_boundary.pdf` (135 KB, 2 pages)
**Purpose:** Test image/figure handling when spanning page boundaries

**Expected behavior:**
- Pipeline should detect image continues across pages
- Should mark with `is_truncated=true` / `is_continuation=true` flags
- Boundary reconciliation should merge or link the image blocks
- Should produce accurate figure description in final Markdown

**What to check:**
```bash
python3 -c "
import json
data = json.loads(open('output/production_pipeline/01_image_across_page_boundary/raw_blocks.json').read())
for b in data:
    if 'figure' in b['block_type'] or 'image' in str(b).lower():
        print(f'{b[\"block_type\"]:12} | page {b[\"page_number\"]} | trunc={b[\"is_truncated\"]} | cont={b[\"is_continuation\"]}')
"
```

---

### 2. `02_table_across_page_boundary.pdf` (6.5 KB)
**Purpose:** Test table handling when spanning page boundaries

**Expected behavior:**
- Pipeline should detect table continues across pages
- Mark boundaries with `is_truncated=true` / `is_continuation=true`
- Boundary reconciliation should **merge table rows** back together
- Final Markdown should have **single complete table**, not split

**What to check:**
```bash
# View final Markdown
cat output/production_pipeline/02_table_across_page_boundary/output.md | grep -A 10 "|"

# Check if table was merged
python3 -c "
import json
data = json.loads(open('output/production_pipeline/02_table_across_page_boundary/raw_blocks.json').read())
tables = [b for b in data if b['block_type'] == 'table']
print(f'Total table blocks: {len(tables)}')
for i, t in enumerate(tables):
    content = json.loads(t['content']) if isinstance(t['content'], str) else t['content']
    print(f'  Table {i}: {len(content)} rows')
"
```

---

### 3. `03_image_across_chunk_boundary_same_page.pdf` (83 KB)
**Purpose:** Test image handling when chunk boundary falls within a page

**Expected behavior:**
- Single page may split across 2 chunks
- Image boundary reconciliation should detect overlap/duplication
- Should remove duplicate blocks from context overlap
- Final output should have clean image description without duplication

**What to check:**
```bash
# Check chunk plans
python3 -c "
import json
plans = json.loads(open('output/production_pipeline/03_image_across_chunk_boundary_same_page/profiles/chunk_plans.json').read())
for i, p in enumerate(plans):
    print(f'Chunk {i}: target_pages={p[\"target_pages\"]}, context_before={p[\"context_before\"]}, context_after={p[\"context_after\"]}')
"

# Check if duplicates were removed
python3 -c "
import json
data = json.loads(open('output/production_pipeline/03_image_across_chunk_boundary_same_page/raw_blocks.json').read())
figures = [b for b in data if b['block_type'] == 'figure']
print(f'Total figure blocks: {len(figures)}')
print(f'Suppress in output: {sum(1 for f in figures if f[\"metadata\"].get(\"suppress_in_output\"))}')
"
```

---

### 4. `04_50_page_mixed_boundary_stress.pdf` (129 KB, 50 pages)
**Purpose:** Stress test with many boundary conditions

**Expected behavior:**
- 50 pages should chunk into 2-3 chunks
- Multiple boundary reconciliation events
- All chunks should extract successfully
- No boundary_risks should remain unresolved

**What to check:**
```bash
# See chunking strategy
python3 -c "
import json
profile = json.loads(open('output/production_pipeline/04_50_page_mixed_boundary_stress/profiles/doc_profile.json').read())
plans = json.loads(open('output/production_pipeline/04_50_page_mixed_boundary_stress/profiles/chunk_plans.json').read())
print(f'Total pages: {profile[\"total_pages\"]}')
print(f'Total chunks: {len(plans)}')
for i, p in enumerate(plans):
    print(f'  Chunk {i}: pages {p[\"target_pages\"][0]}-{p[\"target_pages\"][-1]} ({len(p[\"target_pages\"])} pages)')
"

# Check boundary reconciliation
python3 -c "
import json
risks = json.loads(open('output/production_pipeline/04_50_page_mixed_boundary_stress/boundaries/boundary_risks.json').read())
print(f'Total boundary risks detected: {len(risks)}')
resolved = sum(1 for r in risks if r['resolved'])
print(f'Resolved: {resolved}/{len(risks)}')
for r in risks[:5]:
    print(f'  - Chunk {r[\"chunk_index\"]}: {r[\"risk_type\"]} → {r[\"resolution\"]}')
"
```

---

## Success Criteria

✓ **Image boundaries (01, 03):**
- Figures should have descriptive content
- No missing or duplicated figure descriptions
- `is_truncated` and `is_continuation` flags should be set correctly

✓ **Table boundaries (02):**
- Final Markdown should show single merged table
- All rows should be intact
- Header should appear once only

✓ **Stress test (04):**
- All 50 pages extracted successfully
- Chunks properly sized
- Boundary reconciliation handles all edge cases
- Final Markdown is clean and complete

---

## Running the Tests

```bash
# Run all boundary tests (excluding Salesforce)
python3 run_prod_pipeline.py --exclude-salesforce -v

# Run only boundary tests
python3 run_prod_pipeline.py \
  --include 01_image \
  --include 02_table \
  --include 03_image_across \
  --include 04_50_page \
  -v

# Append to your log
python3 run_prod_pipeline.py --exclude-salesforce -v >> prod_pipeline.txt
```

---

## Output Structure

For each test, you get:
```
output/production_pipeline/{test_name}/
├── output.md                      # Final Markdown (what to inspect)
├── raw_blocks.json                # All blocks with metadata
├── blocks/chunk_*.json            # Per-chunk raw extractions
├── profiles/
│   ├── doc_profile.json
│   ├── chunk_plans.json
│   └── ...
└── boundaries/
    └── boundary_risks.json        # Reconciliation decisions
```

---

## Interpreting Results

### Good Results ✓
- Figures described completely without duplication
- Tables merged across boundaries with all rows intact
- All chunks extracted successfully
- `boundary_risks.json` shows all risks as `resolved: true`
- Final `output.md` is clean and reads naturally

### Issues to Watch ⚠️
- **Duplicate figure descriptions** → overlap not removed properly
- **Split tables** → merge logic didn't trigger
- **Extraction failures** → `[EXTRACTION FAILED: chunk N]` placeholders
- **Unresolved boundary risks** → manual intervention needed
- **Missing content** → `is_truncated/is_continuation` flags not working

---

## Debugging Commands

```bash
# Quick check: how many blocks per type?
python3 -c "
import json
data = json.loads(open('output/production_pipeline/DOCNAME/raw_blocks.json').read())
from collections import Counter
types = Counter(b['block_type'] for b in data)
for t, count in sorted(types.items()):
    print(f'{t:15} {count:3}')
"

# Which blocks were suppressed in output?
python3 -c "
import json
data = json.loads(open('output/production_pipeline/DOCNAME/raw_blocks.json').read())
suppressed = [b['block_id'] for b in data if b['metadata'].get('suppress_in_output')]
print(f'Suppressed blocks: {len(suppressed)}')
for bid in suppressed[:5]:
    print(f'  - {bid}')
"

# Final output character count
wc -c output/production_pipeline/DOCNAME/output.md
```
