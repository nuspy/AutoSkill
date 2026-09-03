import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { API_BASE } from "@/api/client";
import { useSession } from "@/stores/session";

export interface ServerEvent {
  type: string;
  data: Record<string, unknown>;
  at: string;
}

/**
 * Subscribe to a server-sent event stream. EventSource cannot send headers, so the
 * access token is passed as a query parameter handled by the backend proxy in dev and
 * by the same-origin cookie session in production deployments.
 */
export function useServerEvents(path: string | null, onEvent: (event: ServerEvent) => void) {
  const token = useSession((s) => s.accessToken);
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!path || !token || typeof EventSource === "undefined") return;
    const url = `${API_BASE}${path}?access_token=${encodeURIComponent(token)}`;
    const source = new EventSource(url, { withCredentials: true });
    const handler = (e: MessageEvent) => {
      try {
        const parsed = JSON.parse(e.data) as ServerEvent;
        onEvent(parsed);
      } catch {
        /* ignore malformed */
      }
    };
    for (const type of ["notification.created", "job.updated", "checkpoint.waiting", "trial.updated"]) {
      source.addEventListener(type, handler as EventListener);
    }
    return () => source.close();
  }, [path, token, onEvent, queryClient]);
}
