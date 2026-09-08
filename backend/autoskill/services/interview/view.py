"""A small projection of the knowledge document for the read-only interview calls.

`supervise` and `ask` decide what to ask next; they never rewrite the document, so they do not need
its long prose — the step descriptions and decision rules, the edge-case handling narratives, which
together are the bulk of a document once it has grown. Handing them the whole thing meant every one of
those calls carried tens of thousands of characters of context it did not use. This keeps every key,
title, condition, open question and gate-relevant flag the next question is actually chosen from, and
drops the rest, taking a ~28k-character document down to a few thousand.

`ingest` is deliberately not given this view: it is the one call that edits the content, so it keeps
the full document.
"""

from __future__ import annotations

from typing import Any


def _pick(item: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: item[k] for k in keys if k in item}


def compact_view(doc: dict[str, Any]) -> dict[str, Any]:
    """The document with its heavy prose fields dropped, everything else kept."""
    out = dict(doc)
    step_keys = ("key", "title", "kind_hint", "uses", "side_effects", "unclear")
    out["steps"] = [_pick(s, step_keys) for s in doc.get("steps", [])]
    out["edge_cases"] = [_pick(e, ("condition", "confirmed", "source_ref")) for e in doc.get("edge_cases", [])]
    for io_field in ("inputs", "outputs", "glossary"):
        out[io_field] = [_pick(it, ("name", "description")) for it in doc.get(io_field, [])]
    return out
