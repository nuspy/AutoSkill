/**
 * The page's side of the browser extension, and the reason every command stays visible without it.
 *
 * A browser cannot write to `~/.hermes/skills/` or start a process, so the extension is not an
 * alternative implementation of the CLI — it is a way to ask a local helper to run the very command
 * the page is already showing. Which means the rule for every caller is the same: render the command,
 * and offer to run it only when something is actually there to run it.
 *
 * The channel is `window.postMessage` over the page's own origin. There is deliberately no function
 * injected into the page: an injected bridge is callable by every script on the origin, whereas a
 * message the content script filters by origin, source and frame is not.
 */

const CHANNEL = "autoskill";
const TIMEOUT_MS = 10 * 60 * 1000; // an install downloads and unpacks; a minute is not enough

export type Progress = (message: string) => void;

export type LocalFailure = { code: string; message: string; details?: Record<string, unknown> };

export class LocalAgentError extends Error {
  code: string;
  details?: Record<string, unknown>;
  constructor({ code, message, details }: LocalFailure) {
    super(message);
    this.code = code;
    this.details = details;
  }
}

/** Present only when the extension put its marker on the document — never assumed. */
export function extensionVersion(): string | null {
  if (typeof document === "undefined") return null;
  return document.documentElement.dataset.autoskillExtension ?? null;
}

let nextId = 1;

/** Ask the local helper to perform one operation, reporting progress until it answers. */
export function runLocal<T = unknown>(op: string, params: Record<string, unknown> = {}, onProgress?: Progress) {
  return new Promise<T>((resolve, reject) => {
    if (!extensionVersion()) {
      reject(new LocalAgentError({ code: "no_extension", message: "the AutoSkill extension is not installed here" }));
      return;
    }
    const id = nextId++;
    const done = (fn: () => void) => {
      window.removeEventListener("message", listener);
      clearTimeout(timer);
      fn();
    };
    const listener = (event: MessageEvent) => {
      if (event.source !== window || event.origin !== window.location.origin) return;
      const data = event.data;
      if (!data || data.channel !== CHANNEL || data.id !== id) return;
      if (data.direction === "progress") {
        onProgress?.(String(data.message ?? ""));
        return;
      }
      if (data.direction !== "response") return;
      if (data.ok) done(() => resolve(data.result as T));
      else done(() => reject(new LocalAgentError({ code: data.code ?? "error", message: data.message ?? "failed", details: data.details })));
    };
    // A helper that never answers must not leave the button spinning for ever: the person still has
    // the command in front of them, and a stuck spinner is worse than a refusal they can act on.
    const timer = setTimeout(
      () => done(() => reject(new LocalAgentError({ code: "timeout", message: "the local helper did not answer" }))),
      TIMEOUT_MS,
    );
    window.addEventListener("message", listener);
    window.postMessage({ channel: CHANNEL, direction: "request", id, op, params }, window.location.origin);
  });
}

export type MachineAgent = {
  id: string;
  display_name: string;
  detected: boolean;
  base: string;
  base_source: string;
  skill_dir: string;
  mcp_config: string;
  companion: string | null;
};

export type MachineState = {
  cli_version: string;
  server_url: string | null;
  logged_in: boolean;
  device_id: string | null;
  config_path: string;
  agents: MachineAgent[];
  trials: { id: string; skill: string | null; version: string | null; target: string | null }[];
  installs: string[];
};
