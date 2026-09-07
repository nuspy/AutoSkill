"""Scripts or MCP: what the analysis says a version can be delivered as."""

import pytest

from autoskill.core.errors import Conflict, ValidationFailed
from autoskill.models.skill_version import SkillVersion, StepDefinition
from autoskill.services import delivery


def step(key: str, **kw) -> StepDefinition:
    defaults = dict(
        skill_version_id="v1",
        ordinal=1,
        key=key,
        title=key.replace("-", " "),
        instruction="do the thing",
        kind="deterministic",
        side_effects="read_only",
        requires_explicit_auth=False,
    )
    return StepDefinition(**{**defaults, **kw})


def test_a_read_only_step_is_a_script():
    v = delivery.verdict_for(step("open-file"))
    assert not v.needs_mcp and v.reasons == []


def test_irreversible_and_explicit_auth_need_per_action_authorisation():
    assert delivery.verdict_for(step("delete-rows", side_effects="irreversible")).reasons == ["authorization"]
    assert delivery.verdict_for(step("send", requires_explicit_auth=True)).reasons == ["authorization"]


def test_talking_to_a_remote_system_is_not_a_reason_for_mcp():
    """An HTTP call is the same line of Python in a script or in a tool: it decides nothing."""
    remote_step = step("push-to-crm", instruction="upload the rows to the Acme CRM REST API")
    assert delivery.verdict_for(remote_step).reasons == []


async def test_set_delivery_refuses_script_when_a_step_forces_mcp(monkeypatch):
    version = SkillVersion(id="v1", skill_id="s1", version="1.0.0", major=1, minor=0, patch=0)

    async def fake_analyse(_session, _version):
        return delivery.DeliveryAnalysis(
            delivery="mcp",
            steps=[delivery.StepVerdict("send", "Send", "deterministic", "irreversible", ["authorization"])],
            agents_without_shell=[],
        )

    monkeypatch.setattr(delivery, "analyse", fake_analyse)
    with pytest.raises(Conflict) as err:
        await delivery.set_delivery(None, version, "script")
    assert err.value.details["steps"] == ["send"]

    with pytest.raises(ValidationFailed):
        await delivery.set_delivery(None, version, "carrier-pigeon")
