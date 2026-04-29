# LlamaParse Extraction Results

## Summary
LlamaParse was successfully run on the 4 smaller test documents. The 1,130-page Salesforce PDF exceeded LlamaParse's 1,000-page limit and failed.

## Results by Document

| Document | Pages | Size | Status | Chars | Notes |
|---|---|---|---|---|---|
| PerformanceCharts.pdf | 1 | 502 KB | ✓ Success | 2,717 | Chart-heavy document |
| LabReport.pdf | 2 | 225 KB | ✓ Success | 3,247 | Medical report |
| Invoice.jpg | 1 | 101 KB | ✓ Success | 1,028 | Insurance invoice |
| AccidentStatement.pdf | 1 | 1.1 MB | ✓ Success | 6,267 | Complex form with structured data |
| salesforce_release_notes_3-25-2026.pdf | 1,130 | 43 MB | ✗ Failed | 0 | Exceeds 1,000-page limit |

## Key Findings

### Successful Extractions
LlamaParse produced clean, well-structured markdown output:
- **AccidentStatement**: Extracted all form fields, checkboxes, vehicle info, driver details, remarks, and embedded images
- **LabReport**: Extracted medical report with structured formatting
- **Invoice**: Successfully parsed insurance invoice details
- **PerformanceCharts**: Extracted chart descriptions and data

### Large Document Limitation
- **Salesforce PDF (1,130 pages)**: Failed with error: "Document is too large: 1130 pages (max allowed is 1000 for this configuration). Try client side partitioning (see SDK doc)"
- LlamaParse enforces a hard 1,000-page limit per document
- Workaround: Would need client-side partitioning (splitting into smaller chunks before API submission)

## Output Files
All extracted Markdown files are in: `/Users/madhurimachakraborty/document_parser/output/llamaparse/`

