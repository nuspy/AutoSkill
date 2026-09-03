import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { TokenResponse, User } from "@/api/types";
import { useSession } from "@/stores/session";

export function useLogin() {
  const setSession = useSession((s) => s.setSession);
  return useMutation({
    mutationFn: (body: { email: string; password: string }) =>
      api<TokenResponse>("/auth/login", { method: "POST", body, auth: false }),
    onSuccess: (data) => setSession(data.access_token, data.user),
  });
}

export function useRegister() {
  const setSession = useSession((s) => s.setSession);
  return useMutation({
    mutationFn: (body: { email: string; password: string; display_name: string; locale: string; invite_token?: string }) =>
      api<TokenResponse>("/auth/register", { method: "POST", body, auth: false }),
    onSuccess: (data) => setSession(data.access_token, data.user),
  });
}

export function useLogout() {
  const clear = useSession((s) => s.clear);
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<{ ok: boolean }>("/auth/logout", { method: "POST" }),
    onSettled: () => {
      clear();
      qc.clear();
    },
  });
}

export function useUpdateProfile() {
  const setUser = useSession((s) => s.setUser);
  return useMutation({
    mutationFn: (body: { display_name?: string; locale?: string }) => api<User>("/users/me", { method: "PATCH", body }),
    onSuccess: (user) => setUser(user),
  });
}

export function useChangePassword() {
  return useMutation({
    mutationFn: (body: { current_password: string; new_password: string }) =>
      api<{ ok: boolean }>("/users/me/password", { method: "POST", body }),
  });
}

export function useInvitation(token: string) {
  return useQuery({ queryKey: ["invite", token], queryFn: () => api<{ email: string; role: string | null; project: string | null }>(`/auth/invite/${token}`, { auth: false }), enabled: !!token, retry: false });
}

export function useForgotPassword() {
  return useMutation({ mutationFn: (body: { email: string }) => api<{ ok: boolean }>("/auth/password/forgot", { method: "POST", body, auth: false }) });
}

export function useResetPassword() {
  return useMutation({ mutationFn: (body: { token: string; new_password: string }) => api<{ ok: boolean }>("/auth/password/reset", { method: "POST", body, auth: false }) });
}
