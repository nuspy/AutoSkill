import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { Attachment, DataSource, InterviewDetail, InterviewSession, InterviewStep, KnowledgeDoc, MemoryEntry, Skill } from "@/api/types";

export const skillKeys = {
  list: (projectId: string) => ["projects", projectId, "skills"] as const,
  one: (id: string) => ["skills", id] as const,
  memory: (id: string, status: string) => ["skills", id, "memory", status] as const,
  knowledge: (id: string) => ["skills", id, "knowledge"] as const,
  interview: (id: string) => ["interviews", id] as const,
  interviewSteps: (id: string) => ["interviews", id, "steps"] as const,
  interviews: (projectId: string, skillId?: string) => ["projects", projectId, "interviews", skillId ?? ""] as const,
  dataSources: (projectId: string) => ["projects", projectId, "data-sources"] as const,
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

// An interview lasts as long as it takes a person to answer, so its page stays open across tab
// switches, sleeping laptops and — in development — a backend that restarts under it. Three settings
// earn their place, and each one is a bug that happened:
//
// * `refetchInterval` is never `false` for a session still in progress. It used to stop as soon as
//   the page believed a question was on screen, which made the page's own belief the thing that kept
//   it informed: one reset connection while it was waiting and it never asked again, showing a
//   spinner over a snapshot from before the answer arrived. Asking every ten seconds while a human
//   types costs nothing and makes drifting impossible.
// * `refetchOnWindowFocus` overrides the app-wide `false`: coming back to the tab is exactly when
//   "did it move on?" matters.
// * `refetchIntervalInBackground` keeps a throttled tab asking, slowly, instead of not at all.
const FINISHED_STATES = new Set(["complete", "failed", "abandoned"]);
const WORKING_STATES = new Set(["created", "intake", "exploring", "gating", "drafting_requested"]);

/** How often to ask, given what the server last said. Slow while a person types, never off before the end. */
export function interviewPollMs(state: string | undefined): number | false {
  if (state && FINISHED_STATES.has(state)) return false;
  return state && WORKING_STATES.has(state) ? 2500 : 10_000;
}

export function useInterview(sessionId: string) {
  return useQuery({
    queryKey: skillKeys.interview(sessionId),
    queryFn: () => api<InterviewDetail>(`/interviews/${sessionId}`),
    enabled: !!sessionId,
    // Derived from the data on every tick rather than held in component state: a page that remembers
    // how often to ask can be talked out of asking by one failed request, and then nothing is left to
    // tell it otherwise.
    refetchInterval: (query) => interviewPollMs(query.state.data?.session.state),
    refetchOnWindowFocus: true,
    refetchIntervalInBackground: true,
  });
}

export function useInterviewSteps(sessionId: string, enabled: boolean, refetchInterval: number | false) {
  return useQuery({
    queryKey: skillKeys.interviewSteps(sessionId),
    queryFn: () => api<InterviewStep[]>(`/interviews/${sessionId}/steps`),
    enabled: !!sessionId && enabled,
    refetchInterval,
    refetchOnWindowFocus: true,
    refetchIntervalInBackground: true,
  });
}

export function useUploadAttachment(projectId: string) {
  return useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api<Attachment>(`/projects/${projectId}/attachments`, { method: "POST", body: form });
    },
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
  const answer = useMutation({ mutationFn: (body: { text: string; attachments?: Attachment[] }) => api(`/interviews/${sessionId}/answer`, { method: "POST", body }), onSuccess: invalidate });
  const confirm = useMutation({ mutationFn: (body: { confirmed: boolean; text?: string }) => api(`/interviews/${sessionId}/confirm`, { method: "POST", body }), onSuccess: invalidate });
  const abandon = useMutation({ mutationFn: () => api(`/interviews/${sessionId}/abandon`, { method: "POST" }), onSuccess: invalidate });
  const retry = useMutation({ mutationFn: () => api(`/interviews/${sessionId}/retry`, { method: "POST" }), onSuccess: invalidate });
  const invalidateAll = () => {
    invalidate();
    qc.invalidateQueries({ queryKey: skillKeys.interviewSteps(sessionId) });
  };
  const replay = useMutation({ mutationFn: (ordinal: number) => api(`/interviews/${sessionId}/steps/${ordinal}/replay`, { method: "POST" }), onSuccess: invalidateAll });
  const acceptReplay = useMutation({ mutationFn: () => api(`/interviews/${sessionId}/replay/accept`, { method: "POST" }), onSuccess: invalidateAll });
  const discardReplay = useMutation({ mutationFn: () => api(`/interviews/${sessionId}/replay/discard`, { method: "POST" }), onSuccess: invalidateAll });
  return { answer, confirm, abandon, retry, replay, acceptReplay, discardReplay };
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

