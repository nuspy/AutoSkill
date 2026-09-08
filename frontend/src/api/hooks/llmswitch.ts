import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { LlmSwitchModels, LlmSwitchState, LlmSwitchTestResult } from "@/api/types";

export const llmSwitchKey = ["llmswitch"] as const;

export function useLlmSwitch() {
  return useQuery({ queryKey: llmSwitchKey, queryFn: () => api<LlmSwitchState>("/llmswitch") });
}

export interface ProviderFields {
  type?: string;
  name?: string;
  base_url?: string;
  model?: string;
  api_key?: string;
}

/** Every write answers with the whole state, so the screen needs no second round trip. */
export function useLlmSwitchMutations() {
  const qc = useQueryClient();
  const store = (state: LlmSwitchState) => qc.setQueryData(llmSwitchKey, state);

  const create = useMutation({
    mutationFn: (body: ProviderFields) => api<LlmSwitchState>("/llmswitch/providers", { method: "POST", body }),
    onSuccess: store,
  });
  const update = useMutation({
    mutationFn: ({ id, ...body }: ProviderFields & { id: string }) =>
      api<LlmSwitchState>(`/llmswitch/providers/${id}`, { method: "PATCH", body }),
    onSuccess: store,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api<LlmSwitchState>(`/llmswitch/providers/${id}`, { method: "DELETE" }),
    onSuccess: store,
  });
  const assign = useMutation({
    mutationFn: (body: { purpose: string; provider: string | null }) =>
      api<LlmSwitchState>("/llmswitch/assign", { method: "POST", body }),
    onSuccess: store,
  });
  const test = useMutation({
    mutationFn: (id: string) => api<LlmSwitchTestResult>(`/llmswitch/providers/${id}/test`, { method: "POST" }),
  });
  const models = useMutation({
    mutationFn: ({ id, refresh }: { id: string; refresh?: boolean }) =>
      api<LlmSwitchModels>(`/llmswitch/providers/${id}/models${refresh ? "?refresh=true" : ""}`),
  });
  // The same list, but from a provider that is not saved yet: the add form asks the address and key,
  // then fetches the models so a person picks one instead of typing an id they do not know.
  const probeModels = useMutation({
    mutationFn: (fields: { type: string; base_url?: string; api_key?: string }) =>
      api<LlmSwitchModels>("/llmswitch/probe-models", { method: "POST", body: JSON.stringify(fields) }),
  });
  const reload = useMutation({
    mutationFn: () => api<{ ok: boolean }>("/llmswitch/reload", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: llmSwitchKey }),
  });

  return { create, update, remove, assign, test, models, probeModels, reload };
}
