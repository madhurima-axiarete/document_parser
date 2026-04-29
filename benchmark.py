"""
benchmark.py

Evaluates document extraction methods on cost, latency, and large-document viability.

Usage:
    python benchmark.py

Outputs:
    - Summary table to stdout
    - Detailed results to output/benchmark_results.json

Pricing (as of 2025):
    Claude Sonnet 4.6:   $3.00/M input tokens, $15.00/M output tokens
    Landing AI:          ~$0.01/page (configurable via LANDING_AI_PRICE_PER_PAGE env var)
    LlamaParse agentic:  ~$0.003/page (configurable via LLAMAPARSE_PRICE_PER_PAGE env var)
                         See https://cloud.llamaindex.ai/usage for actual rates
    Databricks:          N/A (depends on workspace DBU rates for Serverless SQL)
    pdfminer:            $0.00 (local processing)
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

import claude_extractor
import landing_ai_extractor
import databricks_extractor
import llamaparse_extractor
import pdfminer_extractor

# ── Pricing constants ──────────────────────────────────────────────────────────

CLAUDE_INPUT_COST_PER_M = 3.00  # USD per million input tokens
CLAUDE_OUTPUT_COST_PER_M = 15.00  # USD per million output tokens
LANDING_AI_PRICE_PER_PAGE = float(os.getenv("LANDING_AI_PRICE_PER_PAGE", "0.01"))
LLAMAPARSE_PRICE_PER_PAGE = float(os.getenv("LLAMAPARSE_PRICE_PER_PAGE", "0.003"))

# ── Test file configuration ────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent

SMALL_TEST_FILES = [
    BASE_DIR / "test_docs" / "PerformanceCharts.pdf",
    BASE_DIR / "test_docs" / "LabReport.pdf",
    BASE_DIR / "test_docs" / "Invoice.jpg",
    BASE_DIR / "test_docs" / "AccidentStatement.pdf",
]

LARGE_PDF = BASE_DIR / "test_docs" / "salesforce_release_notes_3-25-2026.pdf"
LARGE_PDF_SAMPLE_PAGES = 10

OUTPUT_DIR = BASE_DIR / "output"

# ── Image extensions ──────────────────────────────────────────────────────────

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


# ── Claude usage capture patch ─────────────────────────────────────────────────

_claude_usage_capture: dict = {"input_tokens": 0, "output_tokens": 0}


def _patched_stream_text(client, messages: list) -> str:
    """Drop-in replacement for claude_extractor._stream_text that captures usage."""
    with client.messages.stream(
        model=claude_extractor._MODEL,
        max_tokens=claude_extractor._MAX_TOKENS,
        messages=messages,
    ) as stream:
        final_msg = stream.get_final_message()
        _claude_usage_capture["input_tokens"] = final_msg.usage.input_tokens
        _claude_usage_capture["output_tokens"] = final_msg.usage.output_tokens
        text_blocks = [b.text for b in final_msg.content if b.type == "text"]
        return "".join(text_blocks)


claude_extractor._stream_text = _patched_stream_text


# ── BenchmarkResult dataclass ──────────────────────────────────────────────────


@dataclass
class BenchmarkResult:
    method: str
    file_name: str
    file_size_mb: float
    page_count: int
    elapsed_seconds: Optional[float]
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    estimated_cost_usd: Optional[float] = None
    cost_note: str = ""
    output_chars: int = 0
    succeeded: bool = False
    error: Optional[str] = None
    notes: str = ""


# ── Helper functions ───────────────────────────────────────────────────────────

_page_count_cache: dict[Path, int] = {}


def _get_page_count(file_path: Path) -> int:
    """Return page count: 1 for images, actual count for PDFs."""
    if file_path in _page_count_cache:
        return _page_count_cache[file_path]

    if file_path.suffix.lower() in IMAGE_EXTS:
        count = 1
    else:
        try:
            from pdfminer.pdfpage import PDFPage

            with open(file_path, "rb") as f:
                count = sum(1 for _ in PDFPage.get_pages(f, check_extractable=False))
        except Exception:
            count = 0

    _page_count_cache[file_path] = count
    return count


def _extract_pdf_pages(file_path: Path, n_pages: int) -> bytes:
    """Extract the first n_pages from a PDF and return as raw bytes."""
    import pypdf

    reader = pypdf.PdfReader(str(file_path))
    writer = pypdf.PdfWriter()
    for i in range(min(n_pages, len(reader.pages))):
        writer.add_page(reader.pages[i])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _calc_claude_cost(input_tokens: int, output_tokens: int) -> float:
    """Return total USD cost for a Claude API call."""
    return (
        input_tokens * CLAUDE_INPUT_COST_PER_M / 1_000_000
        + output_tokens * CLAUDE_OUTPUT_COST_PER_M / 1_000_000
    )


def _calc_landing_ai_cost(page_count: int) -> float:
    """Return estimated USD cost for Landing AI based on page count."""
    return page_count * LANDING_AI_PRICE_PER_PAGE


def _calc_llamaparse_cost(page_count: int) -> float:
    """Return estimated USD cost for LlamaParse based on page count."""
    return page_count * LLAMAPARSE_PRICE_PER_PAGE


# ── Per-method benchmark wrappers ──────────────────────────────────────────────


def _benchmark_claude(file_path: Path) -> BenchmarkResult:
    """Run claude_extractor with usage capture."""
    file_size_mb = file_path.stat().st_size / (1024 * 1024)
    page_count = _get_page_count(file_path)

    _claude_usage_capture["input_tokens"] = 0
    _claude_usage_capture["output_tokens"] = 0

    start = time.time()
    try:
        result = claude_extractor.extract(str(file_path))
        elapsed = time.time() - start
        succeeded = not result.get("warnings") or not any(
            "error" in w.lower() or "not set" in w.lower()
            for w in result.get("warnings", [])
        )
        error = result.get("warnings", [None])[0] if not succeeded else None
        output_chars = result.get("raw_text_chars", 0)
    except Exception as exc:
        elapsed = time.time() - start
        succeeded = False
        error = str(exc)
        output_chars = 0

    input_tok = _claude_usage_capture["input_tokens"]
    output_tok = _claude_usage_capture["output_tokens"]
    cost = _calc_claude_cost(input_tok, output_tok) if succeeded else None
    cost_note = (
        f"${cost:.4f} (in={input_tok:,} × $3/M + out={output_tok:,} × $15/M)"
        if cost is not None
        else "N/A"
    )

    return BenchmarkResult(
        method="claude",
        file_name=file_path.name,
        file_size_mb=round(file_size_mb, 3),
        page_count=page_count,
        elapsed_seconds=round(elapsed, 2),
        input_tokens=input_tok,
        output_tokens=output_tok,
        estimated_cost_usd=cost,
        cost_note=cost_note,
        output_chars=output_chars,
        succeeded=succeeded,
        error=error,
    )


def _benchmark_landing_ai(file_path: Path) -> BenchmarkResult:
    """Run landing_ai_extractor with wall-clock timing."""
    file_size_mb = file_path.stat().st_size / (1024 * 1024)
    page_count = _get_page_count(file_path)

    start = time.time()
    try:
        result = landing_ai_extractor.extract(str(file_path))
        elapsed = time.time() - start
        succeeded = not result.get("warnings") or not any(
            "error" in w.lower() or "not set" in w.lower()
            for w in result.get("warnings", [])
        )
        error = result.get("warnings", [None])[0] if not succeeded else None
        output_chars = result.get("raw_text_chars", 0)
    except Exception as exc:
        elapsed = time.time() - start
        succeeded = False
        error = str(exc)
        output_chars = 0

    cost = _calc_landing_ai_cost(page_count) if succeeded else None
    cost_note = (
        f"~${cost:.4f} est. ({page_count} pages × ${LANDING_AI_PRICE_PER_PAGE}/page — "
        f"see landing.ai/pricing)"
        if cost is not None
        else "N/A"
    )

    return BenchmarkResult(
        method="landing_ai",
        file_name=file_path.name,
        file_size_mb=round(file_size_mb, 3),
        page_count=page_count,
        elapsed_seconds=round(elapsed, 2),
        input_tokens=None,
        output_tokens=None,
        estimated_cost_usd=cost,
        cost_note=cost_note,
        output_chars=output_chars,
        succeeded=succeeded,
        error=error,
    )


def _benchmark_llamaparse(file_path: Path) -> BenchmarkResult:
    """Run llamaparse_extractor with wall-clock timing."""
    file_size_mb = file_path.stat().st_size / (1024 * 1024)
    page_count = _get_page_count(file_path)

    start = time.time()
    try:
        result = llamaparse_extractor.extract(str(file_path))
        elapsed = time.time() - start
        succeeded = not result.get("warnings") or not any(
            "error" in w.lower() or "not set" in w.lower()
            for w in result.get("warnings", [])
        )
        error = result.get("warnings", [None])[0] if not succeeded else None
        output_chars = result.get("raw_text_chars", 0)
    except Exception as exc:
        elapsed = time.time() - start
        succeeded = False
        error = str(exc)
        output_chars = 0

    cost = _calc_llamaparse_cost(page_count) if succeeded else None
    cost_note = (
        f"~${cost:.4f} est. ({page_count} pages × ${LLAMAPARSE_PRICE_PER_PAGE}/page — "
        f"see cloud.llamaindex.ai/usage)"
        if cost is not None
        else "N/A"
    )

    return BenchmarkResult(
        method="llamaparse",
        file_name=file_path.name,
        file_size_mb=round(file_size_mb, 3),
        page_count=page_count,
        elapsed_seconds=round(elapsed, 2),
        input_tokens=None,
        output_tokens=None,
        estimated_cost_usd=cost,
        cost_note=cost_note,
        output_chars=output_chars,
        succeeded=succeeded,
        error=error,
    )


def _benchmark_databricks(file_path: Path) -> BenchmarkResult:
    """Run databricks_extractor with wall-clock timing."""
    file_size_mb = file_path.stat().st_size / (1024 * 1024)
    page_count = _get_page_count(file_path)

    start = time.time()
    try:
        result = databricks_extractor.extract(str(file_path))
        elapsed = time.time() - start
        succeeded = not result.get("warnings") or not any(
            "error" in w.lower()
            or "not set" in w.lower()
            or "credentials" in w.lower()
            for w in result.get("warnings", [])
        )
        error = result.get("warnings", [None])[0] if not succeeded else None
        output_chars = result.get("raw_text_chars", 0)
    except Exception as exc:
        elapsed = time.time() - start
        succeeded = False
        error = str(exc)
        output_chars = 0

    return BenchmarkResult(
        method="databricks",
        file_name=file_path.name,
        file_size_mb=round(file_size_mb, 3),
        page_count=page_count,
        elapsed_seconds=round(elapsed, 2),
        input_tokens=None,
        output_tokens=None,
        estimated_cost_usd=None,
        cost_note="N/A — depends on Databricks DBU rates for Serverless SQL (workspace-specific)",
        output_chars=output_chars,
        succeeded=succeeded,
        error=error,
    )


def _benchmark_pdfminer(file_path: Path) -> BenchmarkResult:
    """Run pdfminer_extractor (local, zero API cost)."""
    file_size_mb = file_path.stat().st_size / (1024 * 1024)
    page_count = _get_page_count(file_path)

    start = time.time()
    try:
        result = pdfminer_extractor.extract(str(file_path))
        elapsed = time.time() - start
        succeeded = bool(
            result.get("raw_text_chars", 0) > 0 or result.get("sections")
        )
        error = result.get("warnings", [None])[0] if result.get("warnings") else None
        output_chars = result.get("raw_text_chars", 0)
    except Exception as exc:
        elapsed = time.time() - start
        succeeded = False
        error = str(exc)
        output_chars = 0

    return BenchmarkResult(
        method="pdfminer",
        file_name=file_path.name,
        file_size_mb=round(file_size_mb, 3),
        page_count=page_count,
        elapsed_seconds=round(elapsed, 2),
        input_tokens=None,
        output_tokens=None,
        estimated_cost_usd=0.0,
        cost_note="$0.00 — local processing, no API",
        output_chars=output_chars,
        succeeded=succeeded,
        error=error,
    )


# ── Large PDF handler ──────────────────────────────────────────────────────────


def _benchmark_large_pdf_claude() -> list[BenchmarkResult]:
    """
    Run two Claude tests on the Salesforce PDF:
    1. Full file — expected to fail (42.8 MB, 1130 pages exceeds API limits)
    2. First 10 pages sample — expected to succeed; extrapolate cost to full doc
    """
    results = []

    if not LARGE_PDF.exists():
        return []

    full_page_count = _get_page_count(LARGE_PDF)
    full_size_mb = LARGE_PDF.stat().st_size / (1024 * 1024)

    # ── Test 1: Full file ──────────────────────────────────────────────────────

    _claude_usage_capture["input_tokens"] = 0
    _claude_usage_capture["output_tokens"] = 0
    start = time.time()
    try:
        result = claude_extractor.extract(str(LARGE_PDF))
        elapsed = time.time() - start
        warnings = result.get("warnings", [])
        succeeded = not warnings or not any("error" in w.lower() for w in warnings)
        error = warnings[0] if warnings else None
        output_chars = result.get("raw_text_chars", 0)
    except Exception as exc:
        elapsed = time.time() - start
        succeeded = False
        error = str(exc)
        output_chars = 0

    input_tok = _claude_usage_capture["input_tokens"]
    output_tok = _claude_usage_capture["output_tokens"]
    cost = _calc_claude_cost(input_tok, output_tok) if succeeded else None

    results.append(
        BenchmarkResult(
            method="claude",
            file_name=LARGE_PDF.name,
            file_size_mb=round(full_size_mb, 1),
            page_count=full_page_count,
            elapsed_seconds=round(elapsed, 2),
            input_tokens=input_tok or None,
            output_tokens=output_tok or None,
            estimated_cost_usd=cost,
            cost_note=f"${cost:.4f}" if cost else "N/A — API rejected file",
            output_chars=output_chars,
            succeeded=succeeded,
            error=error,
            notes=f"FULL FILE: {full_size_mb:.1f} MB, {full_page_count} pages — expected to fail (exceeds 32 MB / 100-page API limit)",
        )
    )

    # ── Test 2: 10-page sample ─────────────────────────────────────────────────

    import tempfile

    sample_bytes = _extract_pdf_pages(LARGE_PDF, LARGE_PDF_SAMPLE_PAGES)
    sample_size_mb = len(sample_bytes) / (1024 * 1024)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(sample_bytes)
        tmp_path = Path(tmp.name)

    _claude_usage_capture["input_tokens"] = 0
    _claude_usage_capture["output_tokens"] = 0
    start = time.time()
    try:
        result = claude_extractor.extract(str(tmp_path))
        elapsed = time.time() - start
        warnings = result.get("warnings", [])
        succeeded = not warnings or not any("error" in w.lower() for w in warnings)
        error = warnings[0] if warnings else None
        output_chars = result.get("raw_text_chars", 0)
    except Exception as exc:
        elapsed = time.time() - start
        succeeded = False
        error = str(exc)
        output_chars = 0
    finally:
        tmp_path.unlink(missing_ok=True)

    input_tok = _claude_usage_capture["input_tokens"]
    output_tok = _claude_usage_capture["output_tokens"]
    cost_sample = _calc_claude_cost(input_tok, output_tok) if succeeded else None
    cost_full_extrap = (
        (cost_sample / LARGE_PDF_SAMPLE_PAGES * full_page_count)
        if cost_sample
        else None
    )

    cost_note = (
        f"${cost_sample:.4f} for {LARGE_PDF_SAMPLE_PAGES} pages; "
        f"extrapolated full-doc cost: ~${cost_full_extrap:.2f}"
        if cost_sample
        else "N/A"
    )

    results.append(
        BenchmarkResult(
            method="claude",
            file_name=LARGE_PDF.name,
            file_size_mb=round(sample_size_mb, 3),
            page_count=LARGE_PDF_SAMPLE_PAGES,
            elapsed_seconds=round(elapsed, 2),
            input_tokens=input_tok,
            output_tokens=output_tok,
            estimated_cost_usd=cost_sample,
            cost_note=cost_note,
            output_chars=output_chars,
            succeeded=succeeded,
            error=error,
            notes=f"10-PAGE SAMPLE of {full_page_count}-page document; extrapolated full cost: ~${cost_full_extrap:.2f}"
            if cost_full_extrap
            else f"10-PAGE SAMPLE of {full_page_count}-page document",
        )
    )

    return results


# ── Output formatting ──────────────────────────────────────────────────────────


def _print_benchmark_table(results: list[BenchmarkResult]) -> None:
    try:
        from rich.table import Table
        from rich.console import Console

        console = Console()
        table = Table(title="Benchmark Results", show_lines=True)
        table.add_column("Method", style="bold", min_width=12)
        table.add_column("File", min_width=26)
        table.add_column("Size (MB)", justify="right")
        table.add_column("Pages", justify="right")
        table.add_column("Time (s)", justify="right")
        table.add_column("In Tokens", justify="right")
        table.add_column("Out Tokens", justify="right")
        table.add_column("Cost (USD)", justify="right")
        table.add_column("Chars Out", justify="right")
        table.add_column("Status")
        table.add_column("Notes")

        for r in results:
            table.add_row(
                r.method,
                r.file_name,
                str(r.file_size_mb),
                str(r.page_count),
                f"{r.elapsed_seconds:.1f}" if r.elapsed_seconds else "—",
                f"{r.input_tokens:,}" if r.input_tokens else "—",
                f"{r.output_tokens:,}" if r.output_tokens else "—",
                f"${r.estimated_cost_usd:.4f}"
                if r.estimated_cost_usd is not None
                else "N/A",
                f"{r.output_chars:,}",
                "[green]OK[/green]" if r.succeeded else "[red]FAIL[/red]",
                r.notes or r.error or "",
            )
        console.print(table)
    except ImportError:
        print("\nMethod | File | MB | Pages | Secs | InTok | OutTok | Cost | Chars | OK | Notes")
        for r in results:
            cost_str = (
                f"${r.estimated_cost_usd:.4f}"
                if r.estimated_cost_usd is not None
                else "N/A"
            )
            print(
                f"{r.method} | {r.file_name} | {r.file_size_mb} | {r.page_count} | "
                f"{r.elapsed_seconds} | {r.input_tokens or ''} | {r.output_tokens or ''} | "
                f"{cost_str} | {r.output_chars} | {r.succeeded} | {r.notes or r.error or ''}"
            )


# ── Main orchestrator ──────────────────────────────────────────────────────────


def run() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    all_results: list[BenchmarkResult] = []

    BENCHMARK_METHODS = [
        ("pdfminer", _benchmark_pdfminer),
        ("landing_ai", _benchmark_landing_ai),
        ("llamaparse", _benchmark_llamaparse),
        ("claude", _benchmark_claude),
        ("databricks", _benchmark_databricks),
    ]

    # ── Small test files — all methods ─────────────────────────────────────────

    print("\n=== Benchmarking small test documents ===\n")
    for file_path in SMALL_TEST_FILES:
        if not file_path.exists():
            print(f"  [SKIP] {file_path.name} — file not found")
            continue
        for method_name, bench_fn in BENCHMARK_METHODS:
            print(
                f"  {method_name:12s} × {file_path.name}...", end=" ", flush=True
            )
            r = bench_fn(file_path)
            all_results.append(r)
            status = "OK" if r.succeeded else "FAIL"
            print(
                f"[{status}] {r.elapsed_seconds:.1f}s  {r.output_chars:,} chars  {r.cost_note}"
            )

    # ── Large PDF — Claude only ────────────────────────────────────────────────

    if LARGE_PDF.exists():
        print(f"\n=== Benchmarking large PDF: {LARGE_PDF.name} ===")
        print(
            "  (Claude only — Landing AI & LlamaParse excluded to avoid excessive API cost)\n"
        )
        large_results = _benchmark_large_pdf_claude()
        all_results.extend(large_results)
        for r in large_results:
            status = "OK" if r.succeeded else "FAIL"
            print(f"  claude  [{status}]  {r.notes}")
            print(
                f"           {r.elapsed_seconds:.1f}s  {r.output_chars:,} chars  {r.cost_note}\n"
            )
    else:
        print(f"\n  [SKIP] {LARGE_PDF.name} — file not found")

    # ── Print summary table ────────────────────────────────────────────────────

    _print_benchmark_table(all_results)

    # ── Save JSON report ───────────────────────────────────────────────────────

    import dataclasses

    report_path = OUTPUT_DIR / "benchmark_results.json"
    report_data = [dataclasses.asdict(r) for r in all_results]
    report_path.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
    print(f"\nDetailed results saved to: {report_path}")


if __name__ == "__main__":
    run()
