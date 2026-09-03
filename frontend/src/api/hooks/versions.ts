import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, API_BASE } from "@/api/client";
import type { LibraryComponent, SkillVersion, SkillVersionDetail, TargetInfo } from "@/api/types";
import { useSession } from "@/stores/session";

export function useVersions(skillId: string) {
  return useQuery({ queryKey: ["skills", skillId, "versions"], queryFn: () => api<SkillVersion[]>(`/skills/${skillId}/versions`), enabled: !!skillId });
}

export function useVersion(versionId: string) {
  return useQuery({ queryKey: ["versions", versionId], queryFn: () => api<SkillVersionDetail>(`/versions/${versionId}`), enabled: !!versionId });
}

export function useVersionFile(versionId: string, path: string | null) {
  return useQuery({
    queryKey: ["versions", versionId, "file", path],
    queryFn: () => api<{ path: string; content: string; size: number; binary: boolean }>(`/versions/${versionId}/files/${path}`),
    enabled: !!versionId && !!path,
  });
}

export function useInstallDoc(versionId: string, target: string, trial = false) {
  return useQuery({
    queryKey: ["versions", versionId, "install", target, trial],
    queryFn: () => api<{ target: string; markdown: string }>(`/versions/${versionId}/install/${target}?trial=${trial}`),
    enabled: !!versionId && !!target,
  });
}

export function useTargets() {
  return useQuery({ queryKey: ["targets"], queryFn: () => api<TargetInfo[]>("/targets"), staleTime: Infinity });
}

export function useGenerateVersion(skillId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { mode: "new" | "patch"; instructions?: string; base_version_id?: string }) => api<{ job_id: string }>(`/skills/${skillId}/versions/generate`, { method: "POST", body }),
    onSuccess: () => setTimeout(() => qc.invalidateQueries({ queryKey: ["skills", skillId, "versions"] }), 1500),
  });
}

export function useDiscardVersion(skillId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (versionId: string) => api<SkillVersion>(`/versions/${versionId}/discard`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["skills", skillId] }),
  });
}

export async function downloadZip(versionId: string, filename: string, targets: string[]) {
  const token = useSession.getState().accessToken;
  const res = await fetch(`${API_BASE}/versions/${versionId}/package.zip?targets=${targets.join(",")}`, { headers: token ? { Authorization: `Bearer ${token}` } : {}, credentials: "include" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function useLibrary(includeDisabled = false) {
  return useQuery({ queryKey: ["library", includeDisabled], queryFn: () => api<LibraryComponent[]>(`/library?include_disabled=${includeDisabled}`) });
}

export function useLibraryMutations() {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ["library"] });
  const create = useMutation({ mutationFn: (body: Partial<LibraryComponent>) => api<LibraryComponent>("/library", { method: "POST", body }), onSuccess: invalidate });
  const update = useMutation({ mutationFn: ({ id, ...body }: Partial<LibraryComponent> & { id: string }) => api<LibraryComponent>(`/library/${id}`, { method: "PUT", body }), onSuccess: invalidate });
  const remove = useMutation({ mutationFn: (id: string) => api(`/library/${id}`, { method: "DELETE" }), onSuccess: invalidate });
  return { create, update, remove };
}
