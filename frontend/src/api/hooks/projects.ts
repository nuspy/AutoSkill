import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { ApiKey, Member, Project, ProjectRole } from "@/api/types";

export const projectKeys = {
  all: ["projects"] as const,
  one: (id: string) => ["projects", id] as const,
  members: (id: string) => ["projects", id, "members"] as const,
  apiKeys: (id: string) => ["projects", id, "api-keys"] as const,
};

export function useProjects() {
  return useQuery({ queryKey: projectKeys.all, queryFn: () => api<Project[]>("/projects") });
}

export function useProject(id: string) {
  return useQuery({ queryKey: projectKeys.one(id), queryFn: () => api<Project>(`/projects/${id}`), enabled: !!id });
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; description?: string }) => api<Project>("/projects", { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: projectKeys.all }),
  });
}

export function useUpdateProject(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name?: string; description?: string; settings?: Record<string, unknown> }) =>
      api<Project>(`/projects/${id}`, { method: "PATCH", body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: projectKeys.one(id) });
      qc.invalidateQueries({ queryKey: projectKeys.all });
    },
  });
}

export function useDeleteProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api<{ ok: boolean }>(`/projects/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: projectKeys.all }),
  });
}

export function useMembers(projectId: string) {
  return useQuery({ queryKey: projectKeys.members(projectId), queryFn: () => api<Member[]>(`/projects/${projectId}/members`) });
}

export function useAddMember(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; role: ProjectRole }) => api<Member>(`/projects/${projectId}/members`, { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: projectKeys.members(projectId) }),
  });
}

export function useUpdateMember(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ memberId, role }: { memberId: string; role: ProjectRole }) =>
      api<Member>(`/projects/${projectId}/members/${memberId}`, { method: "PATCH", body: { role } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: projectKeys.members(projectId) }),
  });
}

export function useRemoveMember(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (memberId: string) => api<{ ok: boolean }>(`/projects/${projectId}/members/${memberId}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: projectKeys.members(projectId) }),
  });
}

export function useProjectApiKeys(projectId: string) {
  return useQuery({ queryKey: projectKeys.apiKeys(projectId), queryFn: () => api<ApiKey[]>(`/projects/${projectId}/api-keys`) });
}

export function useCreateApiKey(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; scopes: string[]; expires_in_days?: number }) =>
      api<ApiKey>(`/projects/${projectId}/api-keys`, { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: projectKeys.apiKeys(projectId) }),
  });
}

export function useRevokeApiKey(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (keyId: string) => api<{ ok: boolean }>(`/api-keys/${keyId}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: projectKeys.apiKeys(projectId) }),
  });
}
