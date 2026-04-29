# How to Run LiteParse on All test_docs Files

## Quick Start

```bash
node liteparse_extractor.js
```

That's it! It will automatically:
1. ✅ Discover all PDF, JPG, PNG, TIFF, BMP files in `test_docs/`
2. ✅ Process them with LiteParse OCR
3. ✅ Save output to `output/liteparse/<filename>.txt`
4. ✅ Print a summary

## What Happens

```
Found 5 file(s) to process:

  • AccidentStatement.pdf
  • Invoice.jpg
  • LabReport.pdf
  • PerformanceCharts.pdf
  • salesforce_release_notes_3-25-2026.pdf

Parsing: AccidentStatement.pdf
  Done in 19.04s
  Saved → output/liteparse/AccidentStatement.txt

Parsing: Invoice.jpg
  Done in 1.65s
  Saved → output/liteparse/Invoice.txt

... (continues for all files)

--- Summary ---
  AccidentStatement.pdf: 19.04s
  Invoice.jpg: 1.65s
  LabReport.pdf: 2.73s
  PerformanceCharts.pdf: 3.15s
  salesforce_release_notes_3-25-2026.pdf: 145.82s
```

## How It Works

The `liteparse_extractor.js` script:

1. **Auto-discovers files** in `test_docs/`
   ```javascript
   const files = readdirSync(TEST_DOCS_DIR);
   const supported = /\.(pdf|jpg|jpeg|png|tiff|bmp)$/i;
   const TEST_FILES = files.filter((f) => supported.test(f)).sort();
   ```

2. **Processes each file**
   ```javascript
   const parser = new LiteParse({ ocrEnabled: true });
   const result = await parser.parse(filePath);
   ```

3. **Saves plain text output**
   ```
   output/liteparse/
   ├── AccidentStatement.txt
   ├── Invoice.txt
   ├── LabReport.txt
   ├── PerformanceCharts.txt
   └── salesforce_release_notes_3-25-2026.txt
   ```

## Add New Files

Just add PDF/image files to `test_docs/` and run again:
```bash
cp MyDocument.pdf test_docs/
node liteparse_extractor.js  # Will automatically include MyDocument.pdf
```

## Performance

| File | Size | Time |
|------|------|------|
| LabReport.pdf | 225 KB | 2.73s |
| PerformanceCharts.pdf | 502 KB | 3.15s |
| AccidentStatement.pdf | 1.1 MB | 19.04s |
| Invoice.jpg | 101 KB | 1.65s |
| salesforce_release_notes_3-25-2026.pdf | 43 MB | 145.82s |

**Total: ~2.5 minutes for 43.8 MB of documents**

## Supported File Types

✅ PDF files (.pdf)
✅ JPEG files (.jpg, .jpeg)
✅ PNG files (.png)
✅ TIFF files (.tiff)
✅ BMP files (.bmp)

Any other file types in `test_docs/` will be ignored.
