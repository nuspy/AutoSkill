import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { Checkpoint, Discussion, Run, RunStep, Trial, TrialCreated, TrialDetail } from "@/api/types";

export function useTrials(skillId?: string, openOnly = false) {
  return useQuery({ queryKey: ["trials", skillId ?? "all", openOnly], queryFn: () => api<Trial[]>(`/trials?${skillId ? `skill_id=${skillId}&` : ""}open_only=${openOnly}`) });
}

export function useTrial(trialId: string, live: boolean) {
  return useQuery({ queryKey: ["trials", trialId], queryFn: () => api<TrialDetail>(`/trials/${trialId}`), enabled: !!trialId, refetchInterval: live ? 3000 : false });
}

export function useCreateTrial() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { skill_version_id: string; target_agent: string; purpose?: string; mode?: string; device_id?: string | null }) => api<TrialCreated>("/trials", { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["trials"] }),
  });
}

export function useTrialActions(trialId: string) {
  const qc = useQueryClient();
  const invalidate = () => { qc.invalidateQueries({ queryKey: ["trials"] }); qc.invalidateQueries({ queryKey: ["skills"] }); };
  const suspend = useMutation({ mutationFn: () => api<Trial>(`/trials/${trialId}/suspend`, { method: "POST" }), onSuccess: invalidate });
  const resume = useMutation({ mutationFn: () => api<Trial>(`/trials/${trialId}/resume`, { method: "POST" }), onSuccess: invalidate });
  const summary = useMutation({ mutationFn: () => api<Trial>(`/trials/${trialId}/summary`, { method: "POST" }), onSuccess: invalidate });
  const outcome = useMutation({ mutationFn: (body: { outcome: string; keep_installed?: boolean; note?: string }) => api<Trial>(`/trials/${trialId}/outcome`, { method: "POST", body }), onSuccess: invalidate });
  const decide = useMutation({ mutationFn: ({ checkpointId, ...body }: { checkpointId: string; decision: string; correction_text?: string; updated_instructions?: string }) => api<Checkpoint>(`/checkpoints/${checkpointId}/decision`, { method: "POST", body }), onSuccess: invalidate });
  const discuss = useMutation({ mutationFn: ({ checkpointId, message }: { checkpointId: string; message: string }) => api<Discussion>(`/checkpoints/${checkpointId}/discussion`, { method: "POST", body: { message } }) });
  const applyDiscussion = useMutation({ mutationFn: (discussionId: string) => api<Discussion>(`/discussions/${discussionId}/apply`, { method: "POST" }), onSuccess: invalidate });
  return { suspend, resume, summary, outcome, decide, discuss, applyDiscussion };
}

export function useRuns(projectId: string, skillId?: string) {
  return useQuery({ queryKey: ["projects", projectId, "runs", skillId ?? ""], queryFn: () => api<Run[]>(`/projects/${projectId}/runs${skillId ? `?skill_id=${skillId}` : ""}`), enabled: !!projectId });
}

export function useRun(runId: string) {
  return useQuery({ queryKey: ["runs", runId], queryFn: () => api<{ run: Run; steps: RunStep[]; checkpoints: Checkpoint[]; annotations: { id: string; kind: string; severity: string | null; text: string; step_key: string | null; created_at: string }[] }>(`/runs/${runId}`), enabled: !!runId });
}

export function useRunFeedback(runId: string) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (body: { human_feedback?: string; is_golden?: boolean }) => api<Run>(`/runs/${runId}`, { method: "PATCH", body }), onSuccess: () => qc.invalidateQueries({ queryKey: ["runs", runId] }) });
}
