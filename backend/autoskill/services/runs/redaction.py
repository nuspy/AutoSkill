"""Best-effort PII/secret redaction and payload capping for telemetry."""

from __future__ import annotations

import json
import re
from typing import Any

PATTERNS = [
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<email>"),
    (re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"), "<iban>"),
    (re.compile(r"(?<!\d)(\+?\d[\d .-]{8,}\d)(?!\d)"), "<phone>"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "<secret>"),
    (re.compile(r"ask_[a-f0-9]{8}_[A-Za-z0-9_\-]{20,}"), "<secret>"),
    (re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key)(\s*[:=]\s*)\S+"), r"\1\2<redacted>"),
]
MAX_STRING = 4000
MAX_PAYLOAD = 64 * 1024


def redact_text(text: str) -> str:
    for pattern, repl in PATTERNS:
        text = pattern.sub(repl, text)
    if len(text) > MAX_STRING:
        text = text[:MAX_STRING] + f"… [truncated {len(text) - MAX_STRING} chars]"
    return text


def redact(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return "<too deep>"
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {str(k)[:120]: redact(v, depth + 1) for k, v in list(value.items())[:200]}
    if isinstance(value, list):
        return [redact(v, depth + 1) for v in value[:200]]
    return value


def cap_payload(value: Any) -> Any:
    encoded = json.dumps(value, ensure_ascii=False, default=str)
    if len(encoded) <= MAX_PAYLOAD:
        return value
    return {"_truncated": True, "preview": encoded[:MAX_PAYLOAD]}
