# Document Parser

Benchmarks three document extraction methods against the same set of test files, writing Markdown output for each.

| Method | What it uses |
|---|---|
| `claude` | Anthropic Claude API — converts any document type to PDF via HTML, then extracts |
| `landing_ai` | [agentic-doc](https://github.com/landing-ai/agentic-doc) SDK |
| `databricks` | Databricks `ai_parse_document` SQL function |

## Setup

```bash
# 1. Clone and enter the repo
git clone <repo-url>
cd document_parser

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Generate sample test files
python create_sample_pptx.py
python create_sample_docx.py

# 5. Configure credentials
cp .env.example .env
# Edit .env and fill in your API keys
```

### Required credentials (`.env`)

| Variable | Where to get it |
|---|---|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com/) → API Keys |
| `LANDING_AI_API_KEY` | [va.landing.ai](https://va.landing.ai/) → Settings → API Keys |
| `DATABRICKS_HOST` | Your Databricks workspace URL |
| `DATABRICKS_TOKEN` | Databricks → User Settings → Access Tokens |
| `DATABRICKS_HTTP_PATH` | Databricks → SQL Warehouses → your warehouse → Connection Details |
| `DATABRICKS_VOLUME_PATH` | Path to a Unity Catalog volume where files will be uploaded |

You only need credentials for the extractors you intend to run. The others will fail gracefully with a warning.

## Usage

Place your test documents in the project root (PDF, JPG, PNG, DOCX), then:

```bash
python run_tests.py
```

Results are written to `output/<method>/<filename>.md`.

## Project structure

```
.
├── run_tests.py                # Orchestrator — runs all extractors and prints a summary table
├── claude_extractor.py         # Anthropic Claude extractor (universal document → PDF → extract)
├── databricks_extractor.py     # Databricks ai_parse_document extractor
├── landing_ai_extractor.py     # Landing AI agentic-doc extractor
├── create_sample_pptx.py       # Generator for sample PPTX test file
├── create_sample_docx.py       # Generator for sample DOCX test file
├── requirements.txt
├── .env.example                # Credential template — copy to .env and fill in
└── output/                     # Generated (git-ignored) — one subfolder per method
```
