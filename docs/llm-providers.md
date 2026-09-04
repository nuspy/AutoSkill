# Which model answers, and who decides

AutoSkill calls a model at five points — `interviewer`, `supervisor`, `author`, `coach`, `analyst`
(the *purposes*). Every call goes through `llm.registry.get_provider(purpose)`, and that function
has exactly one place to look: the **llmswitch registry of the machine the server runs on**.

There used to be an `llm_providers` table, per project and per system, with the API key encrypted in
a column. It is gone (migration `0013`). A model and the key that pays for it belong to the machine
and to whoever administers it, not to a row any project owner can edit; and a database has no way of
knowing what is loaded in the GPU, which subscriptions the machine is already signed in to, or which
CLI agents are on its PATH.

## Resolution

1. the provider assigned to that purpose in the registry;
2. failing that, the one assigned to the `default` consumer;
3. failing that, `no_llm_provider` (409) — nothing runs until an administrator picks one.

If a provider *is* assigned but cannot serve the request — no model configured and nothing loaded,
or a type with no OpenAI-compatible endpoint — the call fails with `llmswitch_provider_unusable`.
There is nothing to fall through to, and there should not be: running the work on a model nobody
chose, at a price nobody agreed to, is the worse outcome.

Tests and `AUTOSKILL_LLM_FAKE` short-circuit all of it with the scripted provider in `llm/fake.py`.

## The registry

`llmswitch` is installed separately (`make llmswitch LLMSWITCH=<path-or-git-url>`, or
`pip install -e <path>` in the backend virtualenv) because it is not on a public index. Without it
the panel says so and no generative step can run, so on a real deployment it is not optional in
practice — only in packaging.

It brings four families of providers:

* **local engines** — LM Studio, vLLM, llama.cpp. A model already in memory is used as it is; a
  second one is never loaded beside it, because on one GPU that does not double the occupancy, it
  fails and takes the running conversation with it. Set `AUTOSKILL_LLMSWITCH_LOAD_MODELS=0` to stop
  the server from loading anything on its own initiative and limit it to what is already warm.
* **pay-per-use keys** — OpenAI, Anthropic, Gemini, Grok, Qwen, Z.AI, DeepSeek, Kimi, Nebius,
  NVIDIA, Unsloth, or any OpenAI-compatible endpoint.
* **subscriptions over HTTP** — the token of an official CLI that is already signed in, renewed
  when it expires.
* **subscriptions through their CLI** — `codex_cli`, `claude_cli`, `antigravity`. These are agents,
  not completion endpoints: seconds per answer, no token counts, no tool protocol. The panel marks
  them, and `Capabilities.tools`/`json_schema` are off so the structured-output ladder falls back to
  asking for fenced JSON.

The registry file holds API keys, so it lives outside the working tree —
`%LOCALAPPDATA%\autoskill\llm_providers.json` on Windows, `~/.config/autoskill/llm_providers.json`
elsewhere. `AUTOSKILL_LLMSWITCH_REGISTRY` overrides the path; on a systemd deployment point it at
something the service user owns, for example `/var/lib/autoskill/llm_providers.json`.

Keys go in through the API and never come out: the state the panel reads says `has_key: true` and
nothing more.

## API

All of it is admin only, under `/api/v1/llmswitch`.

| | |
|---|---|
| `GET /llmswitch` | providers, types, assignments, subscription status, installed CLI agents |
| `POST /llmswitch/providers` | add `{type, name?, base_url?, model?, api_key?}` |
| `PATCH /llmswitch/providers/{id}` | change name, base URL, model, key (an absent key is left alone) |
| `DELETE /llmswitch/providers/{id}` | remove it, and detach every purpose that pointed at it |
| `GET /llmswitch/providers/{id}/models` | what it can serve; `?refresh=true` skips the cache |
| `POST /llmswitch/providers/{id}/test` | reach it and count the models |
| `POST /llmswitch/assign` | `{purpose, provider}`; `provider: null` detaches |
| `POST /llmswitch/reload` | re-read the file after editing it outside the application |

Every write answers with the whole state, so the screen needs no second round trip.

## Adding an adapter

`llm/switch.py` maps the library's `api` field onto the adapters in `llm/adapters/`:
`openai`/`lmstudio`/`vllm`/`gemini` → `OpenAICompatProvider`, `anthropic` → `AnthropicProvider`,
`cli` → `CliAgentProvider`. A type whose `api` is none of these is refused with a message naming it,
which is what happens to Google Cloud Code: it speaks its own protocol, and since 2026 it refuses
individual plans anyway.
