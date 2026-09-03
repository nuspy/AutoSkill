import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { Device, Notification, NotificationPreference } from "@/api/types";

export function useDevices() {
  return useQuery({ queryKey: ["me", "devices"], queryFn: () => api<Device[]>("/me/devices") });
}

export function useRemoveDevice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api<{ ok: boolean }>(`/me/devices/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["me", "devices"] }),
  });
}

export function useNotifications(unreadOnly = false) {
  return useQuery({
    queryKey: ["me", "notifications", unreadOnly],
    queryFn: () => api<{ items: Notification[]; unread: number }>(`/me/notifications?unread_only=${unreadOnly}`),
    refetchInterval: 60_000,
  });
}

export function useMarkRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string | "all") =>
      api<{ ok: boolean }>(id === "all" ? "/me/notifications/read-all" : `/me/notifications/${id}/read`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["me", "notifications"] }),
  });
}

export function useDevicePending(userCode: string) {
  return useQuery({
    queryKey: ["device-pending", userCode],
    queryFn: () => api<{ user_code: string; device_name: string; device_os: string | null; agent_targets: string[]; expires_at: string }>(`/auth/device/pending/${encodeURIComponent(userCode)}`),
    enabled: userCode.length >= 8,
    retry: false,
  });
}

export function useDeviceConfirm() {
  return useMutation({
    mutationFn: (body: { user_code: string; approve: boolean }) => api<{ ok: boolean }>("/auth/device/confirm", { method: "POST", body }),
  });
}

export function useNotificationPreferences() {
  return useQuery({ queryKey: ["me", "notification-preferences"], queryFn: () => api<NotificationPreference[]>("/me/notifications/preferences") });
}

export function useSetNotificationPreference() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { kind: string; in_app: boolean; email: boolean }) => api<{ ok: boolean }>("/me/notifications/preferences", { method: "PUT", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["me", "notification-preferences"] }),
  });
}
