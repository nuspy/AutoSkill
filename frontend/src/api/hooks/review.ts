import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { ReviewBundle, ReviewDecision, ReviewRequest, VersionDiff, VersionTransition } from "@/api/types";

export function useReviewQueue(enabled: boolean, mine = false) {
  return useQuery({ queryKey: ["review", "queue", mine], queryFn: () => api<ReviewRequest[]>(`/review/queue?mine=${mine}`), enabled, refetchInterval: 30_000 });
}

export function useMyReviewRequests() {
  return useQuery({ queryKey: ["review", "mine"], queryFn: () => api<ReviewRequest[]>("/review/mine") });
}

export function useReviewBundle(requestId: string) {
  return useQuery({ queryKey: ["review", requestId], queryFn: () => api<ReviewBundle>(`/review/${requestId}`), enabled: !!requestId });
}

export function useReviewActions(requestId: string) {
  const qc = useQueryClient();
  const invalidate = () => { qc.invalidateQueries({ queryKey: ["review"] }); qc.invalidateQueries({ queryKey: ["skills"] }); qc.invalidateQueries({ queryKey: ["versions"] }); };
  const assign = useMutation({ mutationFn: () => api<ReviewRequest>(`/review/${requestId}/assign`, { method: "POST" }), onSuccess: invalidate });
  const decide = useMutation({ mutationFn: (body: { decision: string; comment?: string; file_comments?: unknown[] }) => api<ReviewDecision>(`/review/${requestId}/decision`, { method: "POST", body }), onSuccess: invalidate });
  const withdraw = useMutation({ mutationFn: () => api<ReviewRequest>(`/review/${requestId}/withdraw`, { method: "POST" }), onSuccess: invalidate });
  return { assign, decide, withdraw };
}

export function useVersionLifecycle(versionId: string, skillId: string) {
  const qc = useQueryClient();
  const invalidate = () => { qc.invalidateQueries({ queryKey: ["skills", skillId] }); qc.invalidateQueries({ queryKey: ["versions", versionId] }); qc.invalidateQueries({ queryKey: ["review"] }); };
  const submit = useMutation({ mutationFn: (summary?: string) => api<ReviewRequest>(`/versions/${versionId}/submit-review`, { method: "POST", body: { summary } }), onSuccess: invalidate });
  const authorize = useMutation({ mutationFn: (body: { action: "publish" | "deprecate"; checklist: Record<string, boolean>; comment?: string }) => api(`/versions/${versionId}/authorize`, { method: "POST", body }), onSuccess: invalidate });
  const transition = useMutation({ mutationFn: (body: { to_state: string; reason?: string }) => api(`/versions/${versionId}/transition`, { method: "POST", body }), onSuccess: invalidate });
  return { submit, authorize, transition };
}

export function useVersionTransitions(versionId: string) {
  return useQuery({ queryKey: ["versions", versionId, "transitions"], queryFn: () => api<VersionTransition[]>(`/versions/${versionId}/transitions`), enabled: !!versionId });
}

export function useVersionDiff(versionId: string, to?: string) {
  return useQuery({ queryKey: ["versions", versionId, "diff", to ?? ""], queryFn: () => api<VersionDiff>(`/versions/${versionId}/diff${to ? `?to=${to}` : ""}`), enabled: !!versionId });
}
