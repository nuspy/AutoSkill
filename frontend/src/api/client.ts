import type { ApiErrorBody, TokenResponse } from "./types";
import { useSession } from "@/stores/session";

export class ApiError extends Error {
  code: string;
  status: number;
  details?: Record<string, unknown>;
  constructor(status: number, body: ApiErrorBody | null) {
    super(body?.error?.message || `HTTP ${status}`);
    this.status = status;
    this.code = body?.error?.code || `http_${status}`;
    this.details = body?.error?.details;
  }
}

const BASE = import.meta.env.VITE_API_BASE || "/api/v1";
let refreshing: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const res = await fetch(`${BASE}/auth/refresh`, { method: "POST", credentials: "include" });
        if (!res.ok) return null;
        const data = (await res.json()) as TokenResponse;
        useSession.getState().setSession(data.access_token, data.user);
        return data.access_token;
      } catch {
        return null;
      } finally {
        setTimeout(() => (refreshing = null), 0);
      }
    })();
  }
  return refreshing;
}

export interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  auth?: boolean;
  retry?: boolean;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, auth = true, retry = true, headers, ...rest } = options;
  const token = useSession.getState().accessToken;
  const init: RequestInit = {
    ...rest,
    credentials: "include",
    headers: {
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(auth && token ? { Authorization: `Bearer ${token}` } : {}),
      ...(headers as Record<string, string>),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  };
  const res = await fetch(`${BASE}${path}`, init);
  if (res.status === 401 && auth && retry) {
    const fresh = await refreshAccessToken();
    if (fresh) return api<T>(path, { ...options, retry: false });
    useSession.getState().clear();
  }
  if (!res.ok) {
    let parsed: ApiErrorBody | null = null;
    try {
      parsed = (await res.json()) as ApiErrorBody;
    } catch {
      /* no body */
    }
    throw new ApiError(res.status, parsed);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export async function bootstrapSession(): Promise<void> {
  const token = await refreshAccessToken();
  if (!token) useSession.getState().clear();
  useSession.getState().setReady();
}

export { BASE as API_BASE };
