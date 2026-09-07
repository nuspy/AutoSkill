"""Scripts or an MCP server: what the trial can tell about a version before it is written.

Scripts are the default. An agent finds a script perfectly well when the skill documents how to call
it — a CLI with `--help` is as readable a contract as a tool schema, and it costs no process and no
room in the model's context. Two situations break that, and only those:

* **authorisation** — a step whose effects are irreversible or that asks for explicit approval. A
  shell command is authorised as "run this command"; a tool can be allowed or denied by name, once,
  and the decision sticks.
* **no shell** — some agents cannot run commands at all. There a script is not inelegant, it is
  unusable, while a registered tool still works.
Talking to a remote system is *not* one of them: an HTTP call to someone else's API is the same
line of Python whether it sits in a script or in a tool.

The analysis names the steps that fall in those cases and leaves the rest as scripts. It never
decides for the person: it says what is forced and what is free, and the choice is made per skill.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.models.skill_version import SkillVersion, StepDefinition
from autoskill.services.targets import all_adapters

DELIVERIES = ("script", "mcp")


@dataclass
class StepVerdict:
    key: str
    title: str
    kind: str
    side_effects: str
    # empty when the step is fine as a script
    reasons: list[str] = field(default_factory=list)

    @property
    def needs_mcp(self) -> bool:
        return bool(self.reasons)


@dataclass
class DeliveryAnalysis:
    delivery: str  # what the version is set to right now
    steps: list[StepVerdict]
    agents_without_shell: list[str]

    @property
    def forced(self) -> bool:
        """True when at least one step cannot be delivered as a script."""
        return any(s.needs_mcp for s in self.steps)

    def as_dict(self) -> dict[str, Any]:
        return {
            "delivery": self.delivery,
            "forced": self.forced,
            "agents_without_shell": self.agents_without_shell,
            "steps": [
                {
                    "key": s.key,
                    "title": s.title,
                    "kind": s.kind,
                    "side_effects": s.side_effects,
                    "needs_mcp": s.needs_mcp,
                    "reasons": s.reasons,
                }
                for s in self.steps
            ],
        }


def verdict_for(step: StepDefinition) -> StepVerdict:
    reasons: list[str] = []
    if step.requires_explicit_auth or step.side_effects == "irreversible":
        reasons.append("authorization")
    return StepVerdict(
        key=step.key,
        title=step.title,
        kind=step.kind,
        side_effects=step.side_effects,
        reasons=reasons,
    )


async def analyse(session: AsyncSession, version: SkillVersion) -> DeliveryAnalysis:
    res = await session.execute(
        select(StepDefinition)
        .where(StepDefinition.skill_version_id == version.id)
        .order_by(StepDefinition.ordinal)
    )
    steps = list(res.scalars().all())
    return DeliveryAnalysis(
        delivery=version.delivery,
        steps=[verdict_for(s) for s in steps if s.kind == "deterministic"],
        agents_without_shell=[a.display_name for a in all_adapters() if not getattr(a, "runs_shell", True)],
    )


async def set_delivery(session: AsyncSession, version: SkillVersion, delivery: str) -> DeliveryAnalysis:
    """Record the choice. 'script' is refused while a step needs per-action authorisation."""
    from autoskill.core.errors import Conflict, ValidationFailed

    if delivery not in DELIVERIES:
        raise ValidationFailed("unknown_delivery", allowed=list(DELIVERIES))
    analysis = await analyse(session, version)
    if delivery == "script" and analysis.forced:
        blocking = [s.key for s in analysis.steps if s.needs_mcp]
        raise Conflict("steps_require_mcp", steps=blocking)
    version.delivery = delivery
    await session.commit()
    analysis.delivery = delivery
    return analysis
