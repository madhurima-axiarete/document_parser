"""
compare_claude_vs_smart.py

Side-by-side benchmark of claude_extractor vs claude_smart_extractor on the
4 standard test documents.

Measures: latency, input/output tokens, estimated cost, output chars.
For claude_smart, also reports how many pages went to Claude vs native PyMuPDF.

Usage:
    python compare_claude_vs_smart.py

Pricing (Claude Sonnet 4.6 as of 2025):
    Input:  $3.00 / M tokens
    Output: $15.00 / M tokens
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

import claude_extractor
import claude_smart_extractor

BASE_DIR = Path(__file__).parent
TEST_FILES = [
    BASE_DIR / "test_docs" / "LabReport.pdf",
    BASE_DIR / "test_docs" / "PerformanceCharts.pdf",
    BASE_DIR / "test_docs" / "AccidentStatement.pdf",
    BASE_DIR / "test_docs" / "Invoice.jpg",
]
OUTPUT_DIR = BASE_DIR / "output"

CLAUDE_INPUT_CPM  = 3.00   # USD per million input tokens
CLAUDE_OUTPUT_CPM = 15.00  # USD per million output tokens


def _cost(input_tok: int, output_tok: int) -> float:
    return (input_tok * CLAUDE_INPUT_CPM + output_tok * CLAUDE_OUTPUT_CPM) / 1_000_000


# ── Token capture: claude_extractor (single call per file) ────────────────────

_std_usage: dict = {"input": 0, "output": 0}


def _patched_stream_std(client, messages: list) -> str:
    with client.messages.stream(
        model=claude_extractor._MODEL,
        max_tokens=claude_extractor._MAX_TOKENS,
        messages=messages,
    ) as stream:
        msg = stream.get_final_message()
        _std_usage["input"]  += msg.usage.input_tokens
        _std_usage["output"] += msg.usage.output_tokens
        return "".join(b.text for b in msg.content if b.type == "text")


claude_extractor._stream_text = _patched_stream_std


# ── Token capture: claude_smart_extractor (one call per Claude-routed page) ───

_smart_usage: dict = {"input": 0, "output": 0, "claude_pages": [], "native_pages": []}


def _patched_call_page_image(client, png_bytes: bytes, page_num: int, file_name: str) -> str:
    import base64
    with client.messages.stream(
        model=claude_smart_extractor._MODEL,
        max_tokens=claude_smart_extractor._MAX_TOKENS,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.standard_b64encode(png_bytes).decode(),
                    },
                },
                {"type": "text", "text": f"{claude_smart_extractor._EXTRACTION_PROMPT}\n\nDOCUMENT: {file_name}, page {page_num}"},
            ],
        }],
    ) as stream:
        msg = stream.get_final_message()
        _smart_usage["input"]  += msg.usage.input_tokens
        _smart_usage["output"] += msg.usage.output_tokens
        _smart_usage["claude_pages"].append(page_num)
        return "".join(b.text for b in msg.content if b.type == "text")


def _patched_call_image_file(client, content: bytes, ext: str, file_name: str) -> str:
    import base64
    media_types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                   ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}
    with client.messages.stream(
        model=claude_smart_extractor._MODEL,
        max_tokens=claude_smart_extractor._MAX_TOKENS,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_types.get(ext, "image/jpeg"),
                        "data": base64.standard_b64encode(content).decode(),
                    },
                },
                {"type": "text", "text": f"{claude_smart_extractor._EXTRACTION_PROMPT}\n\nDOCUMENT: {file_name}"},
            ],
        }],
    ) as stream:
        msg = stream.get_final_message()
        _smart_usage["input"]  += msg.usage.input_tokens
        _smart_usage["output"] += msg.usage.output_tokens
        _smart_usage["claude_pages"].append(1)
        return "".join(b.text for b in msg.content if b.type == "text")


claude_smart_extractor._call_page_image    = _patched_call_page_image
claude_smart_extractor._call_with_image_file = _patched_call_image_file


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class Run:
    method:       str
    file_name:    str
    elapsed:      float
    input_tok:    int
    output_tok:   int
    cost:         float
    output_chars: int
    succeeded:    bool
    routing:      str = ""   # e.g. "Claude: [1,2]  Native: [3]"
    warnings:     list = field(default_factory=list)


# ── Runners ───────────────────────────────────────────────────────────────────

def _run_standard(file_path: Path) -> Run:
    _std_usage["input"] = _std_usage["output"] = 0
    t = time.time()
    try:
        result = claude_extractor.extract(str(file_path))
        ok = bool(result.get("raw_text_chars", 0))
    except Exception as exc:
        result = {"raw_text_chars": 0, "warnings": [str(exc)]}
        ok = False
    elapsed = time.time() - t

    out_path = OUTPUT_DIR / "claude" / (file_path.stem + ".md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(result.get("raw_markdown", ""), encoding="utf-8")

    return Run(
        method="claude",
        file_name=file_path.name,
        elapsed=round(elapsed, 1),
        input_tok=_std_usage["input"],
        output_tok=_std_usage["output"],
        cost=_cost(_std_usage["input"], _std_usage["output"]),
        output_chars=result.get("raw_text_chars", 0),
        succeeded=ok,
        warnings=result.get("warnings", []),
    )


def _run_smart(file_path: Path) -> Run:
    _smart_usage["input"] = _smart_usage["output"] = 0
    _smart_usage["claude_pages"] = []
    _smart_usage["native_pages"] = []

    t = time.time()
    try:
        result = claude_smart_extractor.extract(str(file_path))
        ok = bool(result.get("raw_text_chars", 0))
    except Exception as exc:
        result = {"raw_text_chars": 0, "warnings": [str(exc)]}
        ok = False
    elapsed = time.time() - t

    out_path = OUTPUT_DIR / "claude_smart" / (file_path.stem + ".md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(result.get("raw_markdown", ""), encoding="utf-8")

    # Parse routing from warnings
    routing_parts = []
    for w in result.get("warnings", []):
        if "Claude (vision)" in w or "Native PyMuPDF" in w:
            routing_parts.append(w)

    return Run(
        method="claude_smart",
        file_name=file_path.name,
        elapsed=round(elapsed, 1),
        input_tok=_smart_usage["input"],
        output_tok=_smart_usage["output"],
        cost=_cost(_smart_usage["input"], _smart_usage["output"]),
        output_chars=result.get("raw_text_chars", 0),
        succeeded=ok,
        routing=" | ".join(routing_parts),
        warnings=[w for w in result.get("warnings", []) if "vision" not in w and "Native" not in w],
    )


# ── Table printer ─────────────────────────────────────────────────────────────

def _print_table(pairs: list[tuple[Run, Run]]) -> None:
    try:
        from rich.table import Table
        from rich.console import Console

        console = Console()
        t = Table(title="claude vs claude_smart", show_lines=True)
        t.add_column("File",          min_width=24)
        t.add_column("Method",        min_width=14)
        t.add_column("Time (s)",      justify="right")
        t.add_column("In tokens",     justify="right")
        t.add_column("Out tokens",    justify="right")
        t.add_column("Cost (USD)",    justify="right")
        t.add_column("Chars out",     justify="right")
        t.add_column("Routing / notes")

        for std, smart in pairs:
            # savings vs standard
            tok_saved  = std.input_tok + std.output_tok - smart.input_tok - smart.output_tok
            cost_saved = std.cost - smart.cost
            pct        = (cost_saved / std.cost * 100) if std.cost else 0

            for run in (std, smart):
                status = "[green]OK[/green]" if run.succeeded else "[red]FAIL[/red]"
                notes  = run.routing if run.method == "claude_smart" else (run.warnings[0][:60] if run.warnings else "")
                t.add_row(
                    run.file_name if run.method == "claude" else "",
                    f"[bold]{run.method}[/bold]",
                    f"{run.elapsed}",
                    f"{run.input_tok:,}",
                    f"{run.output_tok:,}",
                    f"${run.cost:.4f}",
                    f"{run.output_chars:,}",
                    notes,
                )

            savings_note = (
                f"[cyan]smart saves {pct:.0f}% cost  (${cost_saved:.4f})  "
                f"{tok_saved:+,} tokens[/cyan]"
            )
            t.add_row("", savings_note, "", "", "", "", "", "")

        console.print(t)

    except ImportError:
        # Plain fallback
        print(f"\n{'File':<26} {'Method':<14} {'Time':>6} {'InTok':>8} {'OutTok':>8} {'Cost':>8} {'Chars':>7}  Routing")
        print("-" * 110)
        for std, smart in pairs:
            for run in (std, smart):
                print(
                    f"{run.file_name if run.method=='claude' else '':<26} "
                    f"{run.method:<14} {run.elapsed:>6.1f} {run.input_tok:>8,} "
                    f"{run.output_tok:>8,} ${run.cost:>7.4f} {run.output_chars:>7,}  "
                    f"{run.routing or ''}"
                )
            cost_saved = std.cost - smart.cost
            pct = (cost_saved / std.cost * 100) if std.cost else 0
            print(f"  → smart saves {pct:.0f}% (${cost_saved:.4f})\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def run() -> None:
    pairs: list[tuple[Run, Run]] = []

    for fp in TEST_FILES:
        if not fp.exists():
            print(f"[SKIP] {fp.name} — not found")
            continue

        print(f"\n{'─'*50}")
        print(f"  {fp.name}")

        print(f"  claude        ...", end=" ", flush=True)
        std = _run_standard(fp)
        print(f"{'OK' if std.succeeded else 'FAIL'}  {std.elapsed}s  {std.input_tok:,} in / {std.output_tok:,} out  ${std.cost:.4f}")

        print(f"  claude_smart  ...", end=" ", flush=True)
        smart = _run_smart(fp)
        print(f"{'OK' if smart.succeeded else 'FAIL'}  {smart.elapsed}s  {smart.input_tok:,} in / {smart.output_tok:,} out  ${smart.cost:.4f}")
        if smart.routing:
            print(f"    routing: {smart.routing}")

        pairs.append((std, smart))

    print(f"\n{'═'*50}\n")
    _print_table(pairs)

    total_std   = sum(r.cost  for r, _ in pairs)
    total_smart = sum(r.cost  for _, r in pairs)
    total_saved = total_std - total_smart
    print(f"\nTotal cost — claude: ${total_std:.4f}  |  claude_smart: ${total_smart:.4f}  |  saved: ${total_saved:.4f} ({total_saved/total_std*100:.0f}% cheaper)\n")
    print(f"Outputs written to {OUTPUT_DIR}/claude/ and {OUTPUT_DIR}/claude_smart/")


if __name__ == "__main__":
    run()
