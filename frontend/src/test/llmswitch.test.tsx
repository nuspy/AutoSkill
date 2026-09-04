import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { LlmSwitchState } from "@/api/types";
import i18n from "@/i18n";

vi.mock("@/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client");
  return { ...actual, api: vi.fn() };
});

import { api } from "@/api/client";
import { LlmSwitchCard } from "@/features/providers/LlmSwitchCard";

const state: LlmSwitchState = {
  available: true,
  reason: "",
  version: "0.1.0",
  registry_path: "/var/lib/autoskill/llm_providers.json",
  loads_models: true,
  providers: [
    { id: "lmstudio", type: "lmstudio", name: "LM Studio", base_url: "http://127.0.0.1:1234/v1", model: "qwen3", embed_model: "", has_key: false, oauth_account: "", oauth_connected: false, local: true, auth: "none", label: "LM Studio", note: "", realtime: true, command: "" },
    { id: "zai_coding", type: "zai_coding", name: "Z.AI coding", base_url: "", model: "glm-5.2", embed_model: "", has_key: true, oauth_account: "", oauth_connected: false, local: false, auth: "api_key", label: "Z.AI (coding)", note: "", realtime: true, command: "" },
  ],
  types: [
    { type: "lmstudio", label: "LM Studio", auth: "none", local: true, base_url: "http://127.0.0.1:1234/v1", note: "", realtime: true },
    { type: "zai_coding", label: "Z.AI (coding)", auth: "api_key", local: false, base_url: "", note: "", realtime: true },
    { type: "claude_cli", label: "Claude Code", auth: "cli", local: true, base_url: "", note: "", realtime: false },
  ],
  assignments: { default: "lmstudio" },
  consumers: ["interviewer", "supervisor", "author", "coach", "analyst", "default"],
  subscriptions: [],
  agents: [],
};

const mocked = vi.mocked(api);

function draw() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <LlmSwitchCard />
    </QueryClientProvider>,
  );
}

describe("machine providers panel", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    mocked.mockReset();
  });

  it("lists the providers and where each one is used", async () => {
    mocked.mockResolvedValue(state);
    draw();
    expect(await screen.findByText("Z.AI coding")).toBeInTheDocument();
    // A provider that needs a key and has one says so; the key itself is never in the payload.
    expect(screen.getByText("key saved")).toBeInTheDocument();
    expect(screen.getByText("local")).toBeInTheDocument();
    // The assignment already in the registry drives the select and is echoed as a badge on the
    // provider it points at, so both places say "Default".
    expect(screen.getByLabelText("Default")).toHaveValue("lmstudio");
    expect(screen.getAllByText("Default")).toHaveLength(2);
  });

  it("assigning a purpose posts the choice", async () => {
    mocked.mockResolvedValue(state);
    draw();
    await screen.findByText("Z.AI coding");
    fireEvent.change(screen.getByLabelText("Author"), { target: { value: "zai_coding" } });
    await waitFor(() =>
      expect(mocked).toHaveBeenCalledWith("/llmswitch/assign", {
        method: "POST",
        body: { purpose: "author", provider: "zai_coding" },
      }),
    );
  });

  it("says so when the library is missing instead of showing an empty panel", async () => {
    mocked.mockResolvedValue({ ...state, available: false, reason: "ModuleNotFoundError: llmswitch", providers: [] });
    draw();
    expect(await screen.findByText("The llmswitch library is not installed")).toBeInTheDocument();
    expect(screen.getByText("ModuleNotFoundError: llmswitch")).toBeInTheDocument();
  });
});
