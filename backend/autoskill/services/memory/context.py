"""Select active memory for prompts within a token budget."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.models.memory import SkillMemoryEntry
from autoskill.services.memory.store import list_entries

KIND_PRIORITY = [
    "decision",
    "rationale",
    "business_need",
    "integration_note",
    "human_procedure",
    "technical_note",
    "data_note",
    "lesson_learned",
]


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def render_entries(entries: list[SkillMemoryEntry], budget_tokens: int = 2000, step_key: str | None = None) -> str:
    ordered = sorted(
        entries,
        key=lambda e: (
            0 if step_key and e.step_key == step_key else 1,
            KIND_PRIORITY.index(e.kind) if e.kind in KIND_PRIORITY else 99,
            e.created_at,
        ),
    )
    lines: list[str] = []
    used = 0
    for e in ordered:
        line = f"- [{e.kind}{'/' + e.step_key if e.step_key else ''}] {e.title}: {e.body}"
        cost = _estimate_tokens(line)
        if used + cost > budget_tokens:
            break
        lines.append(line)
        used += cost
    return "\n".join(lines)


async def memory_context(
    session: AsyncSession, skill_id: str, *, budget_tokens: int = 2000, step_key: str | None = None
) -> str:
    entries = await list_entries(session, skill_id, status="active")
    return render_entries(entries, budget_tokens=budget_tokens, step_key=step_key)
