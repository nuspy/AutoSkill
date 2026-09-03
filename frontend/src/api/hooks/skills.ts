import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { DataSource, InterviewDetail, InterviewSession, KnowledgeDoc, MemoryEntry, Provider, ProviderTestResult, Skill } from "@/api/types";

export const skillKeys = {
  list: (projectId: string) => ["projects", projectId, "skills"] as const,
  one: (id: string) => ["skills", id] as const,
  memory: (id: string, status: string) => ["skills", id, "memory", status] as const,
  knowledge: (id: string) => ["skills", id, "knowledge"] as const,
  interview: (id: string) => ["interviews", id] as const,
  interviews: (projectId: string, skillId?: string) => ["projects", projectId, "interviews", skillId ?? ""] as const,
  dataSources: (projectId: string) => ["projects", projectId, "data-sources"] as const,
  providers: (projectId?: string) => ["providers", projectId ?? "system"] as const,
};

export function useSkills(projectId: string) {
  return useQuery({ queryKey: skillKeys.list(projectId), queryFn: () => api<Skill[]>(`/projects/${projectId}/skills`), enabled: !!projectId });
}

export function useSkill(skillId: string) {
  return useQuery({ queryKey: skillKeys.one(skillId), queryFn: () => api<Skill>(`/skills/${skillId}`), enabled: !!skillId });
}

export function useUpdateSkill(skillId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { title?: string; summary?: string; tags?: string[] }) => api<Skill>(`/skills/${skillId}`, { method: "PATCH", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["skills", skillId] }),
  });
}

export function useSuspendResumeSkill(skillId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ action, note }: { action: "suspend" | "resume"; note?: string }) =>
      api<Skill>(`/skills/${skillId}/${action}`, { method: "POST", body: action === "suspend" ? { note } : undefined }),
    onSuccess: (skill) => {
      qc.invalidateQueries({ queryKey: ["skills", skillId] });
      qc.invalidateQueries({ queryKey: skillKeys.list(skill.project_id) });
    },
  });
}

export function useKnowledgeHistory(skillId: string) {
  return useQuery({ queryKey: skillKeys.knowledge(skillId), queryFn: () => api<KnowledgeDoc[]>(`/skills/${skillId}/knowledge`), enabled: !!skillId });
}

export function useMemory(skillId: string, status = "active") {
  return useQuery({ queryKey: skillKeys.memory(skillId, status), queryFn: () => api<MemoryEntry[]>(`/skills/${skillId}/memory?status=${status}`), enabled: !!skillId });
}

export function useMemoryMutations(skillId: string) {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ["skills", skillId, "memory"] });
  const create = useMutation({
    mutationFn: (body: { kind: string; title: string; body: string; step_key?: string | null }) => api<MemoryEntry>(`/skills/${skillId}/memory`, { method: "POST", body }),
    onSuccess: invalidate,
  });
  const supersede = useMutation({
    mutationFn: ({ id, ...body }: { id: string; title: string; body: string }) => api<MemoryEntry>(`/skills/${skillId}/memory/${id}/supersede`, { method: "POST", body }),
    onSuccess: invalidate,
  });
  const setStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) => api<MemoryEntry>(`/skills/${skillId}/memory/${id}/status/${status}`, { method: "POST" }),
    onSuccess: invalidate,
  });
  return { create, supersede, setStatus };
}

export function useStartInterview(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { title: string; description: string; language: string; skill_id?: string }) =>
      api<InterviewSession>(`/projects/${projectId}/interviews`, { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: skillKeys.list(projectId) }),
  });
}

export function useInterview(sessionId: string, live: boolean) {
  return useQuery({
    queryKey: skillKeys.interview(sessionId),
    queryFn: () => api<InterviewDetail>(`/interviews/${sessionId}`),
    enabled: !!sessionId,
    refetchInterval: live ? 2500 : false,
  });
}

export function useInterviews(projectId: string, skillId?: string) {
  return useQuery({
    queryKey: skillKeys.interviews(projectId, skillId),
    queryFn: () => api<InterviewSession[]>(`/projects/${projectId}/interviews${skillId ? `?skill_id=${skillId}` : ""}`),
    enabled: !!projectId,
  });
}

export function useInterviewActions(sessionId: string) {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: skillKeys.interview(sessionId) });
  const answer = useMutation({ mutationFn: (text: string) => api(`/interviews/${sessionId}/answer`, { method: "POST", body: { text } }), onSuccess: invalidate });
  const confirm = useMutation({ mutationFn: (body: { confirmed: boolean; text?: string }) => api(`/interviews/${sessionId}/confirm`, { method: "POST", body }), onSuccess: invalidate });
  const abandon = useMutation({ mutationFn: () => api(`/interviews/${sessionId}/abandon`, { method: "POST" }), onSuccess: invalidate });
  return { answer, confirm, abandon };
}

export function useDataSources(projectId: string) {
  return useQuery({ queryKey: skillKeys.dataSources(projectId), queryFn: () => api<DataSource[]>(`/projects/${projectId}/data-sources`), enabled: !!projectId });
}

export function useDataSourceMutations(projectId: string) {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: skillKeys.dataSources(projectId) });
  const create = useMutation({ mutationFn: (body: Partial<DataSource>) => api<DataSource>(`/projects/${projectId}/data-sources`, { method: "POST", body }), onSuccess: invalidate });
  const update = useMutation({ mutationFn: ({ id, ...body }: Partial<DataSource> & { id: string }) => api<DataSource>(`/projects/${projectId}/data-sources/${id}`, { method: "PATCH", body }), onSuccess: invalidate });
  const remove = useMutation({ mutationFn: (id: string) => api(`/projects/${projectId}/data-sources/${id}`, { method: "DELETE" }), onSuccess: invalidate });
  return { create, update, remove };
}

export function useProviders(projectId?: string) {
  return useQuery({ queryKey: skillKeys.providers(projectId), queryFn: () => api<Provider[]>(`/providers${projectId ? `?project_id=${projectId}` : ""}`) });
}

export function useProviderMutations(projectId?: string) {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ["providers"] });
  const suffix = projectId ? `?project_id=${projectId}` : "";
  const create = useMutation({ mutationFn: (body: Record<string, unknown>) => api<Provider>(`/providers${suffix}`, { method: "POST", body }), onSuccess: invalidate });
  const update = useMutation({ mutationFn: ({ id, ...body }: Record<string, unknown> & { id: string }) => api<Provider>(`/providers/${id}`, { method: "PATCH", body }), onSuccess: invalidate });
  const remove = useMutation({ mutationFn: (id: string) => api(`/providers/${id}`, { method: "DELETE" }), onSuccess: invalidate });
  const test = useMutation({ mutationFn: (id: string) => api<ProviderTestResult>(`/providers/${id}/test`, { method: "POST" }), onSuccess: invalidate });
  return { create, update, remove, test };
}
