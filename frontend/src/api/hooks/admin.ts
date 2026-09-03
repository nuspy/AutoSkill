import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { AdminStats, AuditEntry, Job, Page, Project, User, UserRole } from "@/api/types";

export function useAdminStats() {
  return useQuery({ queryKey: ["admin", "stats"], queryFn: () => api<AdminStats>("/admin/stats") });
}

export function useAdminUsers(q: string) {
  return useQuery({ queryKey: ["admin", "users", q], queryFn: () => api<Page<User>>(`/admin/users?q=${encodeURIComponent(q)}`) });
}

export function useAdminUpdateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; role?: UserRole; is_active?: boolean }) =>
      api<User>(`/admin/users/${id}`, { method: "PATCH", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "users"] }),
  });
}

export function useAdminProjects() {
  return useQuery({ queryKey: ["admin", "projects"], queryFn: () => api<Project[]>("/admin/projects") });
}

export function useAdminSettings() {
  return useQuery({ queryKey: ["admin", "settings"], queryFn: () => api<Record<string, unknown>>("/admin/settings") });
}

export function useAdminSaveSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (values: Record<string, unknown>) => api<Record<string, unknown>>("/admin/settings", { method: "PUT", body: { values } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "settings"] }),
  });
}

export function useAdminAudit() {
  return useQuery({ queryKey: ["admin", "audit"], queryFn: () => api<Page<AuditEntry>>("/admin/audit?limit=100") });
}

export function useAdminJobs() {
  return useQuery({ queryKey: ["admin", "jobs"], queryFn: () => api<Page<Job>>("/admin/jobs?limit=100"), refetchInterval: 10_000 });
}
