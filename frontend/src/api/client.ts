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

let silentTimer: ReturnType<typeof setInterval> | null = null;

/**
 * Keep the session from ever expiring under the person while they use it.
 *
 * The access token lives 15 minutes; a step that takes longer — a slow interview, a trial — used to
 * let it lapse mid-wait, and the person was bounced to login. Refreshing it in the background well
 * before it expires means it is always fresh, so from their side it simply never expires. Each
 * refresh rotates the 30-day refresh token forward too, so the session slides along for as long as
 * the tab is open. It only refreshes while a session exists, and shares the single-flight guard
 * above, so it never races an on-demand refresh. Idempotent: calling it twice keeps one timer.
 */
export function startSilentRefresh(everyMs = 10 * 60 * 1000): void {
  if (silentTimer) return;
  silentTimer = setInterval(() => {
    if (useSession.getState().accessToken) void refreshAccessToken();
  }, everyMs);
}

export interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  auth?: boolean;
  retry?: boolean;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, auth = true, retry = true, headers, ...rest } = options;
  const token = useSession.getState().accessToken;
  // a FormData body carries its own multipart boundary: setting Content-Type would break it
  const isForm = body instanceof FormData;
  const init: RequestInit = {
    ...rest,
    credentials: "include",
    headers: {
      ...(body !== undefined && !isForm ? { "Content-Type": "application/json" } : {}),
      ...(auth && token ? { Authorization: `Bearer ${token}` } : {}),
      ...(headers as Record<string, string>),
    },
    body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
  };
  const res = await fetch(`${BASE}${path}`, init);
  if (res.status === 401 && auth && retry) {
    // If the session token already changed while this request was in flight, another request has
    // refreshed it: just retry with the current one. Calling refresh again here is what caused the
    // spurious logout — during a long wait the access token expires, several polling requests 401 at
    // once, and a second refresh fires with the cookie the first one already rotated away. That
    // rotated cookie is invalid, so the refresh 401s and the app logged the person out, even though
    // the new cookie (and session) was perfectly valid. Retrying with the fresh token avoids it.
    const current = useSession.getState().accessToken;
    if (current && current !== token) return api<T>(path, { ...options, retry: false });
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
