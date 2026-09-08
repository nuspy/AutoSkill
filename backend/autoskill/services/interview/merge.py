"""Fold an ingest patch into the knowledge document, in code rather than by regenerating it.

The model returns only what the latest answer changed (a `KnowledgeDocPatch`); this applies it. Every
list is an upsert keyed by the item's natural identity, so a returned item either replaces the one
with the same key (a refinement, a confirmation) or is appended (something new), and everything the
model did not mention stays exactly as it was. Doing the merge here is the whole point: the model no
longer re-emits a document that only grows, which is what made late-interview turns take minutes.
"""

from __future__ import annotations

from pydantic import BaseModel

from autoskill.schemas.knowledge import KnowledgeDocModel, KnowledgeDocPatch


def _norm(text: str) -> str:
    """A key compared without caring about spacing or case, so a re-typed key still matches.

    The model repeats a key verbatim from the document to update an item, but "Sheet1 " and "sheet1"
    are the same source; normalising avoids turning a refinement into a duplicate. A near-miss only
    costs a duplicate entry, never lost data, so a light touch is right here.
    """
    return " ".join(text.split()).casefold()


def _upsert(existing: list[BaseModel], incoming: list[BaseModel], key: str) -> list[BaseModel]:
    """Replace items whose key already exists, append the rest, keep original order."""
    index = {_norm(str(getattr(item, key))): i for i, item in enumerate(existing)}
    out = list(existing)
    for item in incoming:
        k = _norm(str(getattr(item, key)))
        if k in index:
            out[index[k]] = item
        else:
            index[k] = len(out)
            out.append(item)
    return out


def _union(existing: list[str], incoming: list[str]) -> list[str]:
    out = list(existing)
    seen = {_norm(x) for x in out}
    for x in incoming:
        if _norm(x) not in seen:
            seen.add(_norm(x))
            out.append(x)
    return out


def merge_patch(doc: KnowledgeDocModel, patch: KnowledgeDocPatch) -> KnowledgeDocModel:
    """The document with the patch applied — a new model, the input left untouched."""
    d = doc.model_copy(deep=True)

    if patch.task is not None:
        # Field by field, non-empty wins: the model sends only the task fields the answer clarified,
        # and an omitted (empty) field must not blank out what is already known.
        for field in ("name", "goal", "trigger", "actor_role"):
            value = getattr(patch.task, field)
            if value:
                setattr(d.task, field, value)

    if patch.constraints is not None:
        c, pc = d.constraints, patch.constraints
        c.tools_available = _union(c.tools_available, pc.tools_available)
        c.forbidden_actions = _union(c.forbidden_actions, pc.forbidden_actions)
        c.secrets_needed = _union(c.secrets_needed, pc.secrets_needed)
        c.pii = c.pii or pc.pii

    d.data_sources = _upsert(d.data_sources, patch.data_sources, "ref")
    d.inputs = _upsert(d.inputs, patch.inputs, "name")
    d.outputs = _upsert(d.outputs, patch.outputs, "name")
    d.steps = _upsert(d.steps, patch.steps, "key")
    d.edge_cases = _upsert(d.edge_cases, patch.edge_cases, "condition")
    d.acceptance_criteria = _upsert(d.acceptance_criteria, patch.acceptance_criteria, "id")
    d.integrations = _upsert(d.integrations, patch.integrations, "system")
    d.glossary = _upsert(d.glossary, patch.glossary, "name")

    resolved = {_norm(q) for q in patch.resolved_open_questions}
    kept = [q for q in d.open_questions if _norm(q) not in resolved]
    seen = {_norm(q) for q in kept}
    for q in patch.new_open_questions:
        if _norm(q) not in seen:
            seen.add(_norm(q))
            kept.append(q)
    d.open_questions = kept

    return d
