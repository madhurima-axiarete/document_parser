# Extraction Process Logging Guide

## What "Chunk Extraction" Actually Means

When the pipeline logs `Chunk N: pages [...] → API call`, here's what happens:

1. **API Call**: Send chunk (pages + context) to Claude via vision extraction
2. **Parse Response**: Extract JSON blocks from Claude's output
3. **Validate**: Verify all blocks are properly formatted
4. **Return**: Blocks added to results if successful

Each of these steps happens within the single "API call" action.

## Logging Format

### Successful Extraction

```
[2026-05-04 23:03:19]   Chunk 1/7: pages [1, 2, 3, 4, 5, 6, 7, 8] → API call...
[2026-05-04 23:03:45]   Chunk 2/7: pages [9, 10, 11, 12, 13, 14, 15] → API call...
```

Meaning: Chunk was successfully extracted in one attempt.

### Retry on Transient Error

```
[2026-05-04 23:04:10]   Chunk 3/7: pages [16-25] → API call (attempt 1/3)...
[2026-05-04 23:04:15]       Chunk 3: Rate limited, backoff 2s...
[2026-05-04 23:04:17]   Chunk 3/7: pages [16-25] → API call (attempt 2/3)...
```

Meaning: First attempt hit rate limiting. After backoff, retry succeeded.

### Recovered via Splitting

```
[2026-05-04 23:05:20]   Chunk 4/7: pages [26-40] → API call...
[2026-05-04 23:05:21]       Chunk 4: Output too large (15 pages, 28,774 chars), halving to smaller chunks...
[2026-05-04 23:05:21]       → Splitting into 2 chunks: pages [26-32] + [33-40]
[2026-05-04 23:05:25]   Chunk 4/7: pages [26-32] → API call [A]...
[2026-05-04 23:05:30]   Chunk 4/7: pages [33-40] → API call [B]...
```

Meaning: 
- Original 15-page chunk caused response to be unparseable (JSON truncated)
- System automatically split it into 2 smaller chunks
- Both smaller chunks succeeded
- **No warning** — this is expected and handled correctly

### Permanent Failure

```
[2026-05-04 23:06:10]   Chunk 5/7: pages [41-50] → API call (attempt 1/3)...
[2026-05-04 23:06:15]       Chunk 5: Connection timeout, retry 1/3...
[2026-05-04 23:06:20]   Chunk 5/7: pages [41-50] → API call (attempt 2/3)...
[2026-05-04 23:06:25]       Chunk 5: Connection timeout, retry 2/3...
[2026-05-04 23:06:30]   Chunk 5/7: pages [41-50] → API call (attempt 3/3)...
[2026-05-04 23:06:35]       ⚠️  UNRECOVERABLE: Chunk 5 (pages [41-50]): Connection timeout
```

Meaning:
- Chunk failed 3 retries with persistent error
- Cannot be split (not a JSON parsing issue)
- **Warning shown** — this is a real problem
- Placeholder block created so document isn't missing content

## End-of-Run Summary

### ✓ SUCCESS (No Issues)

```
[2026-05-04 23:06:25] ✓ SUCCESS
[2026-05-04 23:06:25]   Time: 402.1s
[2026-05-04 23:06:25]   Cost: $1.409 (133,700 in, 67,208 out)
```

Meaning: All chunks extracted successfully. No warnings. Document is complete.

### ✓ SUCCESS (With Retries/Splits - NO WARNINGS)

```
[2026-05-04 23:06:25] ✓ SUCCESS
[2026-05-04 23:06:25]   Time: 402.1s
[2026-05-04 23:06:25]   Cost: $1.409 (133,700 in, 67,208 out)
```

Meaning: All chunks extracted (some required retry or splitting). All recovered successfully. **No warnings shown** because nothing failed permanently.

### ✓ SUCCESS (With Permanent Failures)

```
[2026-05-04 23:06:25] ✓ SUCCESS
[2026-05-04 23:06:25]   Time: 402.1s
[2026-05-04 23:06:25]   Cost: $1.409 (133,700 in, 67,208 out)
[2026-05-04 23:06:25]   ⚠️  Unrecoverable Issues: 1
[2026-05-04 23:06:25]     - Chunk 5 (pages [41-50]): Connection timeout
```

Meaning: Extraction complete, but 1 chunk had a permanent failure. A placeholder was created for that chunk, so the document has content for all pages but that specific chunk's content is marked as a placeholder.

## Key Principles

| Scenario | Show Warning? | Reason |
|----------|---------------|--------|
| Chunk fails, retried, succeeds | ❌ NO | Recovery was successful |
| Chunk fails JSON parsing, split, both succeed | ❌ NO | Split recovery succeeded |
| Chunk fails after all retries | ✅ YES | Permanent unrecoverable failure |
| Chunk never extracted, placeholder created | ✅ YES | Content missing/placeholder quality |

## What Changed

**Before:**
- Warnings shown for ANY chunk that had an error, even if successfully recovered
- "Extracting chunk" was vague about what was happening
- No indication of retry/splitting strategy

**After:**
- Warnings **only** for permanently unrecoverable failures
- Clear logging showing: `Chunk N: pages [X-Y] → API call (attempt M/N)`
- Explicit messages for halving/splitting with new page ranges
- Success message is clean when all chunks recovered successfully

## Interpreting Warnings

If you see warnings in the output, **every warning represents content that could not be automatically recovered**. The pipeline tried:
1. Retries (up to 3 times)
2. Chunk splitting (for JSON/output size issues)

If it's still failing, it means:
- Network/API issue is persistent
- Chunk cannot be split further (already single-page or below min size)
- Document content genuinely couldn't be extracted for that page range

In all cases, a placeholder block is created so the document structure is complete, but that chunk's content quality is reduced.
