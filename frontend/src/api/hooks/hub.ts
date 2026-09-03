import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { Category, Contribution, CuratedList, HubHome, HubSkill, HubSkillDetail, Installation, MirrorStatus, Rating, Skill } from "@/api/types";

export function useHubHome() {
  return useQuery({ queryKey: ["hub", "home"], queryFn: () => api<HubHome>("/hub") });
}

export function useHubSearch(params: { q?: string; category?: string; tag?: string; sort?: string }) {
  const qs = new URLSearchParams(Object.fromEntries(Object.entries(params).filter(([, v]) => v)) as Record<string, string>).toString();
  return useQuery({ queryKey: ["hub", "search", qs], queryFn: () => api<{ items: HubSkill[]; total: number }>(`/hub/search?${qs}`) });
}

export function useHubSkill(skillId: string) {
  return useQuery({ queryKey: ["hub", "skill", skillId], queryFn: () => api<HubSkillDetail>(`/hub/skills/${skillId}`), enabled: !!skillId });
}

export function useFavorites() {
  return useQuery({ queryKey: ["me", "favorites"], queryFn: () => api<HubSkill[]>("/me/favorites") });
}

export function useToggleFavorite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ skillId, on }: { skillId: string; on: boolean }) => api(`/me/favorites/${skillId}`, { method: on ? "POST" : "DELETE" }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["hub"] }); qc.invalidateQueries({ queryKey: ["me", "favorites"] }); },
  });
}

export function useInstallations() {
  return useQuery({ queryKey: ["me", "installations"], queryFn: () => api<Installation[]>("/me/installations") });
}

export function useInstallationMutations() {
  const qc = useQueryClient();
  const invalidate = () => { qc.invalidateQueries({ queryKey: ["me", "installations"] }); qc.invalidateQueries({ queryKey: ["hub"] }); };
  const register = useMutation({ mutationFn: (body: { skill_version_id: string; target_agent: string; channel?: string; state?: string }) => api<Installation>("/me/installations", { method: "POST", body }), onSuccess: invalidate });
  const remove = useMutation({ mutationFn: (id: string) => api(`/me/installations/${id}`, { method: "DELETE" }), onSuccess: invalidate });
  return { register, remove };
}

export function useFork() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: ({ skillId, ...body }: { skillId: string; target_project_id: string; title?: string }) => api<Skill>(`/skills/${skillId}/fork`, { method: "POST", body }), onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }) });
}

export function usePublishSettings(skillId: string) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (body: { visibility?: string; category_id?: string | null; tags?: string[]; external_remote_url?: string; external_token?: string }) => api<Skill>(`/skills/${skillId}/publish-settings`, { method: "PATCH", body }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["skills", skillId] }); qc.invalidateQueries({ queryKey: ["hub"] }); } });
}

export function useCategories() {
  return useQuery({ queryKey: ["hub", "categories"], queryFn: () => api<Category[]>("/hub/categories") });
}

export function useAdminHub() {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ["hub"] });
  const published = useQuery({ queryKey: ["hub", "admin", "skills"], queryFn: () => api<HubSkill[]>("/admin/hub/skills") });
  const feature = useMutation({ mutationFn: ({ skillId, featured }: { skillId: string; featured: boolean }) => api(`/admin/hub/skills/${skillId}/feature?featured=${featured}`, { method: "POST" }), onSuccess: invalidate });
  const createCategory = useMutation({ mutationFn: (body: { slug: string; name: Record<string, string>; ordinal?: number }) => api<Category>("/admin/hub/categories", { method: "POST", body }), onSuccess: invalidate });
  const deleteCategory = useMutation({ mutationFn: (id: string) => api(`/admin/hub/categories/${id}`, { method: "DELETE" }), onSuccess: invalidate });
  return { published, feature, createCategory, deleteCategory };
}

export function useRate(skillId: string) {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ["hub"] });
  const rate = useMutation({ mutationFn: (body: { stars: number; comment?: string }) => api<Rating>(`/hub/skills/${skillId}/rating`, { method: "PUT", body }), onSuccess: invalidate });
  const unrate = useMutation({ mutationFn: () => api(`/hub/skills/${skillId}/rating`, { method: "DELETE" }), onSuccess: invalidate });
  return { rate, unrate };
}

export function useHubList(slug: string) {
  return useQuery({ queryKey: ["hub", "list", slug], queryFn: () => api<{ list: CuratedList; items: HubSkill[] }>(`/hub/lists/${slug}`), enabled: !!slug });
}

export function useContributions(skillId: string) {
  return useQuery({ queryKey: ["skills", skillId, "contributions"], queryFn: () => api<Contribution[]>(`/skills/${skillId}/contributions`), enabled: !!skillId });
}

export function useContributionMutations(skillId: string) {
  const qc = useQueryClient();
  const invalidate = () => { qc.invalidateQueries({ queryKey: ["skills"] }); qc.invalidateQueries({ queryKey: ["me", "notifications"] }); };
  const contribute = useMutation({ mutationFn: (body: { version_id?: string; message?: string }) => api<Contribution>(`/skills/${skillId}/contribute`, { method: "POST", body }), onSuccess: invalidate });
  const decide = useMutation({ mutationFn: ({ id, ...body }: { id: string; accept: boolean; comment?: string }) => api<Contribution>(`/contributions/${id}/decision`, { method: "POST", body }), onSuccess: invalidate });
  return { contribute, decide };
}

export function useMirror(skillId: string) {
  return useQuery({ queryKey: ["skills", skillId, "mirror"], queryFn: () => api<MirrorStatus>(`/skills/${skillId}/mirror`), enabled: !!skillId });
}

export function useAdminLists() {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ["hub"] });
  const lists = useQuery({ queryKey: ["hub", "admin", "lists"], queryFn: () => api<CuratedList[]>("/admin/hub/lists") });
  const create = useMutation({ mutationFn: (body: { slug: string; name: Record<string, string>; description?: string | null; ordinal?: number; is_public?: boolean }) => api<CuratedList>("/admin/hub/lists", { method: "POST", body }), onSuccess: invalidate });
  const remove = useMutation({ mutationFn: (id: string) => api(`/admin/hub/lists/${id}`, { method: "DELETE" }), onSuccess: invalidate });
  const addItem = useMutation({ mutationFn: ({ listId, skillId }: { listId: string; skillId: string }) => api(`/admin/hub/lists/${listId}/items/${skillId}`, { method: "POST" }), onSuccess: invalidate });
  const removeItem = useMutation({ mutationFn: ({ listId, skillId }: { listId: string; skillId: string }) => api(`/admin/hub/lists/${listId}/items/${skillId}`, { method: "DELETE" }), onSuccess: invalidate });
  const promote = useMutation({ mutationFn: (skillId: string) => api(`/library/from-skill/${skillId}`, { method: "POST" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["library"] }) });
  return { lists, create, remove, addItem, removeItem, promote };
}
