"""Files shared during an interview: stored once, summarised for the model.

The model cannot open a spreadsheet, and asking the person to retype its contents defeats the point
of attaching it. Each upload is therefore reduced to a short textual preview — sheet names, headers,
the first rows — which is what ends up in the prompt (`{name, media_type, preview}`, the shape the
interview templates already expect). The bytes stay in the content store, addressed by hash, so the
same file shared twice costs one copy.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from autoskill.services.storage.content_store import get_content_store

MAX_BYTES = 25 * 1024 * 1024
PREVIEW_CHARS = 2000
PREVIEW_ROWS = 8
TEXT_SUFFIXES = (".txt", ".md", ".log", ".yaml", ".yml", ".ini", ".cfg", ".py", ".js", ".ts", ".sql", ".html", ".xml")


def _decode(data: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return ""


def _clip(text: str) -> str:
    text = text.strip()
    return text if len(text) <= PREVIEW_CHARS else text[:PREVIEW_CHARS] + f"… (+{len(text) - PREVIEW_CHARS} characters)"


def _csv_preview(data: bytes) -> str:
    rows = list(csv.reader(io.StringIO(_decode(data))))
    if not rows:
        return "empty file"
    head = [", ".join(cell for cell in row) for row in rows[:PREVIEW_ROWS]]
    more = f"\n… (+{len(rows) - PREVIEW_ROWS} more rows)" if len(rows) > PREVIEW_ROWS else ""
    return _clip(f"{len(rows)} rows, {len(rows[0])} columns\n" + "\n".join(head) + more)


def _xlsx_preview(data: bytes) -> str:
    try:
        from openpyxl import load_workbook
    except ImportError:  # pragma: no cover - openpyxl is a dependency, this is a safety net
        return "spreadsheet (install openpyxl on the server to read its contents)"
    try:
        book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - a corrupt upload must not break the interview
        return f"spreadsheet that could not be read: {exc}"
    parts: list[str] = []
    for sheet in book.worksheets:
        parts.append(f"sheet '{sheet.title}' ({sheet.max_row or 0} rows x {sheet.max_column or 0} columns)")
        for row in sheet.iter_rows(max_row=PREVIEW_ROWS, values_only=True):
            cells = ["" if v is None else str(v) for v in row]
            if any(cells):
                parts.append("  " + " | ".join(cells))
        if (sheet.max_row or 0) > PREVIEW_ROWS:
            parts.append(f"  … (+{sheet.max_row - PREVIEW_ROWS} more rows)")
    book.close()
    return _clip("\n".join(parts))


def preview_of(filename: str, media_type: str, data: bytes) -> str:
    """A few lines describing what is inside the file, for the prompt."""
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm", ".xltx")):
        return _xlsx_preview(data)
    if name.endswith(".csv") or media_type == "text/csv":
        return _csv_preview(data)
    if name.endswith(".json") or media_type == "application/json":
        try:
            return _clip(json.dumps(json.loads(_decode(data)), ensure_ascii=False, indent=2))
        except (ValueError, TypeError):
            return _clip(_decode(data))
    if name.endswith(TEXT_SUFFIXES) or media_type.startswith("text/"):
        return _clip(_decode(data))
    if media_type.startswith("image/"):
        # no vision model is guaranteed here: say what it is instead of pretending to have read it
        return f"image ({len(data)} bytes) — its contents were not read"
    if name.endswith(".xls"):
        return "legacy Excel file (.xls): save it as .xlsx to let the interview read it"
    if name.endswith(".pdf"):
        return f"PDF document ({len(data)} bytes) — its text was not extracted"
    return f"{media_type or 'unknown type'} ({len(data)} bytes) — contents not read"


def store_attachment(filename: str, media_type: str, data: bytes) -> dict[str, Any]:
    """Keep the bytes and return the descriptor the interview carries around."""
    digest = get_content_store().put(data)
    return {
        "name": filename,
        "media_type": media_type or "application/octet-stream",
        "size": len(data),
        "hash": digest,
        "preview": preview_of(filename, media_type or "", data),
    }
