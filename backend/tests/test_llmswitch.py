"""The machine's providers, configured through llmswitch: API, resolution order, secrets."""

import pytest

from autoskill.config import get_settings
from autoskill.llm import switch
from autoskill.llm.adapters.cli_agent import CliAgentProvider
from autoskill.llm.adapters.openai_compat import OpenAICompatProvider
from autoskill.llm.provider import ChatMessage
from autoskill.llm.registry import NoProviderConfigured, get_provider
from tests.conftest import auth, register

pytestmark = pytest.mark.skipif(not switch.available(), reason="llmswitch is not installed")


@pytest.fixture(autouse=True)
def registry_file(tmp_path, monkeypatch):
    """A registry of its own per test: the real one holds the developer's keys."""
    path = tmp_path / "llm_providers.json"
    monkeypatch.setenv("AUTOSKILL_LLMSWITCH_REGISTRY", str(path))
    get_settings.cache_clear()
    switch.reset_registry()
    yield path
    monkeypatch.delenv("AUTOSKILL_LLMSWITCH_REGISTRY", raising=False)
    get_settings.cache_clear()
    switch.reset_registry()


async def test_admin_configures_a_provider_and_the_key_never_comes_back(app_client, registry_file):
    alice = await register(app_client, "alice@example.com")
    bob = await register(app_client, "bob@example.com")
    a, b = auth(alice["access_token"]), auth(bob["access_token"])

    assert (await app_client.get("/api/v1/llmswitch", headers=b)).status_code == 403

    empty = await app_client.get("/api/v1/llmswitch", headers=a)
    assert empty.status_code == 200
    state = empty.json()
    assert state["available"] is True and state["providers"] == []
    assert "interviewer" in state["consumers"] and "default" in state["consumers"]
    assert any(t["type"] == "lmstudio" for t in state["types"])

    created = await app_client.post(
        "/api/v1/llmswitch/providers",
        json={"type": "openai_compat", "name": "House model", "base_url": "http://127.0.0.1:9/v1", "model": "m1", "api_key": "sk-secret"},
        headers=a,
    )
    assert created.status_code == 201
    provider = created.json()["providers"][0]
    assert provider["has_key"] is True and provider["model"] == "m1"
    assert "sk-secret" not in created.text  # the key stays in the file, outside the answer

    assigned = await app_client.post("/api/v1/llmswitch/assign", json={"purpose": "author", "provider": provider["id"]}, headers=a)
    assert assigned.status_code == 200 and assigned.json()["assignments"]["author"] == provider["id"]

    renamed = await app_client.patch(f"/api/v1/llmswitch/providers/{provider['id']}", json={"name": "Renamed"}, headers=a)
    assert renamed.status_code == 200
    assert renamed.json()["providers"][0] == {**provider, "name": "Renamed"}  # the key survived the edit

    assert (await app_client.patch("/api/v1/llmswitch/providers/nope", json={"name": "x"}, headers=a)).status_code == 404
    bad_type = await app_client.post("/api/v1/llmswitch/providers", json={"type": "not-a-provider"}, headers=a)
    assert bad_type.status_code == 422 and bad_type.json()["error"]["code"] == "unknown_provider_type"

    gone = await app_client.delete(f"/api/v1/llmswitch/providers/{provider['id']}", headers=a)
    assert gone.status_code == 200
    assert gone.json()["providers"] == [] and gone.json()["assignments"] == {}


async def test_unreachable_provider_reports_instead_of_failing(app_client, registry_file):
    alice = await register(app_client, "alice@example.com")
    a = auth(alice["access_token"])
    created = await app_client.post(
        "/api/v1/llmswitch/providers",
        json={"type": "openai_compat", "base_url": "http://127.0.0.1:9/v1", "model": "m1"},
        headers=a,
    )
    pid = created.json()["providers"][0]["id"]

    models = await app_client.get(f"/api/v1/llmswitch/providers/{pid}/models", headers=a)
    assert models.status_code == 200 and models.json()["models"] == [] and models.json()["error"]

    tested = await app_client.post(f"/api/v1/llmswitch/providers/{pid}/test", headers=a)
    assert tested.status_code == 200 and tested.json()["ok"] is False and tested.json()["error"]


async def test_purpose_falls_back_to_the_default_consumer(registry_file):
    reg = switch.registry()
    reg.add({"id": "house", "type": "openai_compat", "base_url": "http://127.0.0.1:9/v1", "model": "m1"})
    reg.assign("default", "house")

    chosen = await switch.provider_for("coach")
    assert chosen is not None
    provider, usage_id = chosen
    assert isinstance(provider, OpenAICompatProvider)
    assert provider.model == "m1" and provider.base_url == "http://127.0.0.1:9/v1"
    assert usage_id == "llmswitch:house"

    reg.add({"id": "special", "type": "openai_compat", "base_url": "http://127.0.0.1:9/v1", "model": "m2"})
    reg.assign("coach", "special")
    provider, _ = await switch.provider_for("coach")
    assert provider.model == "m2"  # its own assignment wins over the fallback


async def test_provider_without_a_model_is_refused_loudly(registry_file):
    reg = switch.registry()
    reg.add({"id": "house", "type": "openai_compat", "base_url": "http://127.0.0.1:9/v1"})
    reg.assign("author", "house")
    with pytest.raises(switch.LlmSwitchUnusable):
        await switch.provider_for("author")


async def test_get_provider_serves_the_assigned_one_and_refuses_when_there_is_none(registry_file):
    """The registry is the only source: an unassigned purpose has nowhere else to fall back to."""
    with pytest.raises(NoProviderConfigured):
        await get_provider("author")

    reg = switch.registry()
    reg.add({"id": "house", "type": "openai_compat", "base_url": "http://127.0.0.1:9/v1", "model": "switch-model"})
    reg.assign("author", "house")

    provider, usage_id = await get_provider("author")
    assert provider.model == "switch-model" and usage_id == "llmswitch:house"

    # Another purpose is still unserved until it is assigned, on its own or through `default`.
    with pytest.raises(NoProviderConfigured):
        await get_provider("analyst")
    reg.assign("default", "house")
    provider, _ = await get_provider("analyst")
    assert provider.model == "switch-model"


async def test_disabled_by_configuration_leaves_every_purpose_unserved(registry_file, monkeypatch):
    reg = switch.registry()
    reg.add({"id": "house", "type": "openai_compat", "base_url": "http://127.0.0.1:9/v1", "model": "m1"})
    reg.assign("author", "house")

    monkeypatch.setenv("AUTOSKILL_LLMSWITCH_ENABLED", "0")
    get_settings.cache_clear()
    switch.reset_registry()

    assert switch.available() is False
    assert await switch.provider_for("author") is None
    with pytest.raises(NoProviderConfigured):
        await get_provider("author")
    state = await switch.state()
    assert state["available"] is False and state["providers"] == []


def test_cli_agent_folds_the_conversation_into_one_prompt():
    """The CLIs are invoked once, not turn by turn: what they get must read as one request."""
    prompt = CliAgentProvider._flatten(
        [
            ChatMessage(role="system", content="Be brief."),
            ChatMessage(role="user", content="Hi"),
            ChatMessage(role="assistant", content="Hello"),
            ChatMessage(role="user", content="   "),
        ]
    )
    assert prompt == "Be brief.\n\nUser: Hi\n\nAssistant: Hello"


async def test_probing_models_before_saving_and_leaving_no_scratch_behind(app_client, registry_file, monkeypatch):
    """The add form asks for a model id nobody memorises, so it must fetch the list from the fields
    typed — before there is a saved provider to point at — and leave the registry as it found it."""
    admin = await register(app_client, "admin@example.com")
    headers = auth(admin["access_token"])

    # The scratch provider is really added and removed by the production code; only the one network
    # call the library would make is replaced, so what is exercised is the add/list/remove dance.
    seen: dict = {}

    def fake_models(self, pid, force=False):
        seen["pid"] = pid
        # the scratch entry exists here — the public listing shows it mid-probe
        seen["present_during"] = pid in {p["id"] for p in self.public().get("providers", [])}
        return [{"id": "great-model"}, {"id": "other-model"}]

    monkeypatch.setattr(switch.registry().__class__, "models", fake_models, raising=True)

    res = await app_client.post(
        "/api/v1/llmswitch/probe-models",
        json={"type": "lmstudio", "base_url": "http://127.0.0.1:1300/v1", "api_key": "k"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert [m["id"] for m in body["models"]] == ["great-model", "other-model"]
    assert seen["present_during"], "the scratch provider existed while it was asked"

    # nothing saved: the providers list is still empty
    state = (await app_client.get("/api/v1/llmswitch", headers=headers)).json()
    assert state["providers"] == [], "the scratch provider was removed, not left behind"


async def test_a_provider_that_cannot_be_reached_answers_with_the_reason(app_client, registry_file, monkeypatch):
    """A half-filled form pointing nowhere is a normal state, not a failed request."""
    admin = await register(app_client, "admin2@example.com")
    headers = auth(admin["access_token"])

    def boom(self, pid, force=False):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(switch.registry().__class__, "models", boom, raising=True)
    res = await app_client.post(
        "/api/v1/llmswitch/probe-models",
        json={"type": "lmstudio", "base_url": "http://127.0.0.1:9/v1"},
        headers=headers,
    )
    assert res.status_code == 200
    assert "connection refused" in res.json()["error"]
    assert (await app_client.get("/api/v1/llmswitch", headers=headers)).json()["providers"] == []
