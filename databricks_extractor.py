"""
databricks_extractor.py

Extracts document content using Databricks ai_parse_document SQL function.

Flow:
  1. Upload file to Unity Catalog Volume via Files API
  2. Execute ai_parse_document SQL via Statement Execution API
  3. Poll until complete
  4. Parse structured elements → render as Markdown in document order

Requires env vars:
  DATABRICKS_HOST        e.g. https://adb-xxxx.cloud.databricks.com
  DATABRICKS_TOKEN       Personal access token (dapi...)
  DATABRICKS_HTTP_PATH   e.g. /sql/1.0/warehouses/abc123
  DATABRICKS_VOLUME_PATH e.g. /Volumes/workspace/default/testing
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

METHOD = "databricks"

_POLL_INTERVAL = 2   # seconds between status checks
_POLL_TIMEOUT  = 120  # seconds before giving up


# ── Credentials ────────────────────────────────────────────────────────────────


def _creds() -> tuple[str, str, str, str]:
    host   = os.getenv("DATABRICKS_HOST", "").rstrip("/")
    token  = os.getenv("DATABRICKS_TOKEN", "")
    http_path   = os.getenv("DATABRICKS_HTTP_PATH", "")
    volume_path = os.getenv("DATABRICKS_VOLUME_PATH", "").rstrip("/")
    return host, token, http_path, volume_path


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _warehouse_id(http_path: str) -> str:
    return http_path.rstrip("/").split("/")[-1]


# ── Step 1: Upload file to UC Volume ──────────────────────────────────────────


def _upload(host: str, token: str, volume_path: str, file_path: Path) -> str:
    """
    Upload file bytes to the UC Volume.
    Returns the full volume file path used in SQL.
    """
    # Files API path strips the leading slash
    api_path = f"{volume_path}/{file_path.name}".lstrip("/")
    url = f"{host}/api/2.0/fs/files/{api_path}"
    resp = requests.put(
        url,
        headers={**_headers(token), "Content-Type": "application/octet-stream"},
        data=file_path.read_bytes(),
        timeout=60,
    )
    resp.raise_for_status()
    return f"{volume_path}/{file_path.name}"


# ── Step 2: Execute SQL ────────────────────────────────────────────────────────


def _execute_sql(host: str, token: str, warehouse_id: str, volume_file_path: str) -> str:
    """Submit the ai_parse_document SQL and return the statement_id."""
    sql = f"""
SELECT to_json(ai_parse_document(
    content,
    map('version', '2.0', 'descriptionElementTypes', '*')
)) AS parsed
FROM READ_FILES('{volume_file_path}', format => 'binaryFile')
""".strip()

    resp = requests.post(
        f"{host}/api/2.0/sql/statements",
        headers=_headers(token),
        json={
            "statement": sql,
            "warehouse_id": warehouse_id,
            "wait_timeout": "10s",
            "on_wait_timeout": "CONTINUE",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["statement_id"]


# ── Step 3: Poll for result ────────────────────────────────────────────────────


def _poll(host: str, token: str, statement_id: str) -> dict:
    """Poll until statement succeeds or fails. Returns the full response dict."""
    deadline = time.time() + _POLL_TIMEOUT
    while time.time() < deadline:
        resp = requests.get(
            f"{host}/api/2.0/sql/statements/{statement_id}",
            headers=_headers(token),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        state = data.get("status", {}).get("state", "")
        if state == "SUCCEEDED":
            return data
        if state in ("FAILED", "CANCELED", "CLOSED"):
            error = data.get("status", {}).get("error", {}).get("message", state)
            raise RuntimeError(f"Statement {state}: {error}")
        time.sleep(_POLL_INTERVAL)
    raise TimeoutError(f"Statement {statement_id} did not complete in {_POLL_TIMEOUT}s")


# ── Step 4: Parse elements → Markdown ─────────────────────────────────────────


def _bbox_comment(el: dict) -> str:
    """Build a Landing AI-style metadata comment from a Databricks element's bbox."""
    etype = el.get("type", "text")
    bbox_list = el.get("bbox") or []
    if not bbox_list:
        return f"<!-- {etype} -->"
    b = bbox_list[0]
    page = b.get("page_id", 0)
    coords = b.get("coord", [])
    if len(coords) == 4:
        x1, y1, x2, y2 = coords
        return f"<!-- {etype}, from page {page} (x1={x1},y1={y1},x2={x2},y2={y2}) -->"
    return f"<!-- {etype}, from page {page} -->"


def _elements_to_markdown(elements: list[dict]) -> str:
    """Convert Databricks document elements (sorted by id) to Markdown with bbox metadata."""
    lines: list[str] = []

    for el in sorted(elements, key=lambda e: e.get("id", 0)):
        etype   = el.get("type", "text")
        content = (el.get("content") or "").strip()
        desc    = (el.get("description") or "").strip()
        meta    = _bbox_comment(el)

        if etype in ("title",):
            if content:
                lines.append(f"# {content} {meta}")

        elif etype in ("section_header",):
            if content:
                lines.append(f"## {content} {meta}")

        elif etype in ("page_header",):
            if content:
                lines.append(f"### {content} {meta}")

        elif etype == "table":
            if content:
                lines.append(f"{content} {meta}")

        elif etype == "figure":
            if desc:
                lines.append(f"> **[Figure]** {desc} {meta}")
            elif content:
                lines.append(f"> {content} {meta}")

        elif etype in ("page_footer", "page_number"):
            pass  # skip navigation noise

        else:
            # text, caption, footnote, list_item, etc.
            if content:
                lines.append(f"{content} {meta}")

        if etype not in ("page_footer", "page_number"):
            lines.append("")

    return "\n".join(lines).strip()


def _parse_result(data: dict) -> str:
    """Extract the JSON string from the statement result and render to Markdown."""
    try:
        rows = data["result"]["data_array"]
        parsed_json_str = rows[0][0]
        doc = json.loads(parsed_json_str)
        elements = doc.get("document", {}).get("elements", [])
        return _elements_to_markdown(elements)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not parse Databricks result: {exc}") from exc


# ── Public interface ───────────────────────────────────────────────────────────


def extract(file_path: str) -> dict:
    """Upload file to Databricks, run ai_parse_document, return Markdown."""
    path = Path(file_path)

    host, token, http_path, volume_path = _creds()
    if not all([host, token, http_path, volume_path]):
        return {
            "file": path.name, "method": METHOD,
            "raw_markdown": "", "raw_text_chars": 0,
            "warnings": ["Databricks credentials not set — check .env"],
        }

    warehouse_id = _warehouse_id(http_path)

    # Try to upload the file; if the token lacks Files API permission,
    # fall back to assuming the file is already in the volume (manual upload).
    volume_file_path = f"{volume_path}/{path.name}"
    try:
        _upload(host, token, volume_path, path)
    except Exception:
        pass  # file is already there from manual upload — continue

    try:
        statement_id = _execute_sql(host, token, warehouse_id, volume_file_path)
        result_data  = _poll(host, token, statement_id)
        raw_markdown = _parse_result(result_data)
    except Exception as exc:
        return {
            "file": path.name, "method": METHOD,
            "raw_markdown": "", "raw_text_chars": 0,
            "warnings": [f"Databricks query failed: {exc}"],
        }

    return {
        "file": path.name,
        "method": METHOD,
        "raw_text_chars": len(raw_markdown),
        "raw_markdown": raw_markdown,
        "warnings": [],
    }
