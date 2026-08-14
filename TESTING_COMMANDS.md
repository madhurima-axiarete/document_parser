# Comprehensive Testing Commands for Salesforce 100-Page Extraction

## Quick Tests

### 1. Verify Pages 75-81 Are Extracted
```bash
python3 -c "
import json
raw = json.loads(open('output/production_pipeline/salesforce_first_100_pages/raw_blocks.json').read())
for p in range(75, 82):
    blocks = [b for b in raw if b['page_number'] == p]
    print(f'Page {p}: {len(blocks)} blocks')
"
```

### 2. Check Marketing Section Content
```bash
grep -A5 "## Marketing" output/production_pipeline/salesforce_first_100_pages/sections/005_how_and_when_do_features_become_availabl.md | head -10
```

### 3. Verify All 100 Pages Extracted
```bash
python3 -c "
import json
raw = json.loads(open('output/production_pipeline/salesforce_first_100_pages/raw_blocks.json').read())
pages = sorted(set(b['page_number'] for b in raw))
print(f'Total pages: {len(pages)}, Range: {min(pages)}-{max(pages)}')
print(f'Missing: {set(range(1, 101)) - set(pages) or \"None\"}')"
```

### 4. Section File Sizes
```bash
ls -lh output/production_pipeline/salesforce_first_100_pages/sections/
```

### 5. Total Block Count
```bash
python3 -c "
import json
raw = json.loads(open('output/production_pipeline/salesforce_first_100_pages/raw_blocks.json').read())
print(f'Total blocks: {len(raw)}')
print(f'Block types: {sorted(set(b[\"block_type\"] for b in raw))}')"
```

## Detailed Tests

### 6. Check Chunk Extraction Status
```bash
python3 << 'PYTHON'
import json
from pathlib import Path
raw = json.loads(Path('output/production_pipeline/salesforce_first_100_pages/raw_blocks.json').read_text())
chunks = {}
for b in raw:
    chunk = b['chunk_id']
    if chunk not in chunks:
        chunks[chunk] = set()
    chunks[chunk].add(b['page_number'])

for chunk_id in sorted(chunks.keys()):
    pages = sorted(chunks[chunk_id])
    print(f"{chunk_id}: pages {min(pages):3d}-{max(pages):3d} ({len(pages):2d} pages)")
PYTHON
```

### 7. Verify Section 005 Content Completeness
```bash
python3 << 'PYTHON'
import re
content = open('output/production_pipeline/salesforce_first_100_pages/sections/005_how_and_when_do_features_become_availabl.md').read()
sections = [
    "## Salesforce Overall",
    "## Agentforce & Einstein",
    "## Automation",
    "## Commerce",
    "## Data 360",
    "## Deployment",
    "## Development",
    "## Experience Cloud",
    "## Field Service",
    "## Industries",
    "## Mobile",
    "## Omnistudio",
    "## Partner Cloud",
    "## Revenue Management",
    "## Sales"
]
missing = [s for s in sections if s not in content]
print(f"Sections present: {len(sections) - len(missing)}/{len(sections)}")
if missing:
    print(f"Missing: {missing}")
else:
    print("✓ All sections present!")
PYTHON
```

### 8. Search for Specific Content
```bash
# Find Analytics content
grep -i "analytics" output/production_pipeline/salesforce_first_100_pages/sections/003_salesforce_release_notes.md | head -3

# Find Marketing content in section 005
grep -i "marketing" output/production_pipeline/salesforce_first_100_pages/sections/005_how_and_when_do_features_become_availabl.md | head -3

# Find a specific feature
grep "Agentforce" output/production_pipeline/salesforce_first_100_pages/sections/005_how_and_when_do_features_become_availabl.md | head -2
```

### 9. Validate JSON Structure
```bash
python3 << 'PYTHON'
import json
try:
    raw = json.loads(open('output/production_pipeline/salesforce_first_100_pages/raw_blocks.json').read())
    print(f"✓ Valid JSON: {len(raw)} blocks")
    
    # Check required fields
    required = {'block_id', 'block_type', 'content', 'page_number', 'chunk_id'}
    sample = raw[0]
    missing = required - set(sample.keys())
    
    if missing:
        print(f"✗ Missing fields in sample: {missing}")
    else:
        print(f"✓ All required fields present")
        
except json.JSONDecodeError as e:
    print(f"✗ Invalid JSON: {e}")
PYTHON
```

### 10. Compare Before/After Fix
```bash
python3 << 'PYTHON'
import json
from pathlib import Path

# Fixed version
fixed = json.loads(Path('output/production_pipeline/salesforce_first_100_pages/raw_blocks.json').read_text())
fixed_pages = len(set(b['page_number'] for b in fixed))
fixed_p75_81 = sum(1 for b in fixed if 75 <= b['page_number'] <= 81)

print(f"Fixed extraction:")
print(f"  Total pages: {fixed_pages}/100")
print(f"  Pages 75-81 blocks: {fixed_p75_81}")
print(f"  Total blocks: {len(fixed)}")
PYTHON
```

## Query Document with Extracted Data

### 11. Search Across All Sections
```bash
# Find all mentions of a topic
grep -r "Tableau" output/production_pipeline/salesforce_first_100_pages/sections/ | head -5

# Find a specific feature in all sections
grep -r "Einstein" output/production_pipeline/salesforce_first_100_pages/sections/ | wc -l
```

### 12. Generate Statistics
```bash
python3 << 'PYTHON'
import json
import os
from pathlib import Path

raw = json.loads(Path('output/production_pipeline/salesforce_first_100_pages/raw_blocks.json').read_text())

# Statistics
print("=" * 50)
print("EXTRACTION STATISTICS")
print("=" * 50)
print(f"Total pages: {len(set(b['page_number'] for b in raw))}")
print(f"Total blocks: {len(raw)}")
print(f"Average blocks per page: {len(raw) / len(set(b['page_number'] for b in raw)):.1f}")

# Block types
types = {}
for b in raw:
    types[b['block_type']] = types.get(b['block_type'], 0) + 1

print(f"\nBlock distribution:")
for bt in sorted(types.keys(), key=lambda x: -types[x]):
    pct = 100 * types[bt] / len(raw)
    print(f"  {bt:15s}: {types[bt]:3d} ({pct:5.1f}%)")

# File sizes
sections_dir = Path('output/production_pipeline/salesforce_first_100_pages/sections')
total_size = sum(f.stat().st_size for f in sections_dir.glob('*.md'))
print(f"\nSection files total: {total_size / 1024:.1f} KB")

# Document info
output_md = Path('output/production_pipeline/salesforce_first_100_pages/output.md')
if output_md.exists():
    print(f"output.md: {output_md.stat().st_size / 1024:.1f} KB")
PYTHON
```

## Run All Tests at Once
```bash
bash test_extraction_quality.sh
```

---

**All tests should pass with ✓ marks indicating successful extraction!**
