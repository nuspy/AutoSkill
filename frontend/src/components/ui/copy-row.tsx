import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, Copy, Play } from "lucide-react";
import { toast } from "sonner";
import { useLocalAgent } from "@/api/hooks/localAgent";
import { Button } from "@/components/ui/button";
import { runLocal } from "@/lib/localAgent";

/** An operation the local helper could perform instead of the person running the command. */
export type LocalAction = { op: string; params?: Record<string, unknown>; onDone?: () => void };

/** A command shown inside a row, where a full CopyRow would dwarf what surrounds it.
 *
 * Same promise as CopyRow — nothing a person is expected to run is shown without a way to take it —
 * in the shape a list item can hold. Several places had reimplemented the block form by hand and
 * several others had simply left the command as text nobody could copy. */
export function CopyInline({ value, label }: { value: string; label?: string }) {
  const { t } = useTranslation(["common"]);
  return (
    <span className="inline-flex min-w-0 items-center gap-1">
      <code className="truncate rounded bg-accent px-1.5 py-0.5 font-mono text-xs" title={value}>{value}</code>
      <Button
        size="icon"
        variant="ghost"
        className="h-6 w-6 shrink-0"
        aria-label={label ?? t("common:actions.copy")}
        title={label ?? t("common:actions.copy")}
        onClick={() => { navigator.clipboard.writeText(value); toast.success(t("common:actions.copied")); }}
      >
        <Copy className="h-3.5 w-3.5" />
      </Button>
    </span>
  );
}

/** A label, a monospace value and a copy button: used for commands and online addresses.
 *
 * With an `action`, and only when the browser helper is installed, it also offers to run the command
 * for the person. The command stays exactly where it was either way: the helper removes a
 * transcription, not the choice, and a machine without it must lose nothing.
 */
export function CopyRow({ label, value, hint, action }: { label?: string; value: string; hint?: string; action?: LocalAction }) {
  const { t } = useTranslation(["common"]);
  const { available } = useLocalAgent();
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const run = async () => {
    if (!action) return;
    setRunning(true);
    setProgress(null);
    try {
      await runLocal(action.op, action.params ?? {}, setProgress);
      toast.success(t("common:localAgent.done"));
      action.onDone?.();
    } catch (err) {
      // Named, because "it failed" leaves the person with a command they no longer trust and no
      // reason not to run it themselves — which is exactly what they should do next.
      toast.error(`${(err as Error).message}`);
    } finally {
      setRunning(false);
      setProgress(null);
    }
  };
  return (
    <div className="space-y-1">
      {label && <p className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</p>}
      <div className="flex items-start gap-2">
        <pre className="flex-1 overflow-x-auto whitespace-pre-wrap break-all rounded-lg bg-accent p-3 font-mono text-xs">{value}</pre>
        {action && available && (
          <Button variant="primary" loading={running} onClick={run} className="shrink-0 whitespace-nowrap">
            <Play className="h-4 w-4" />
            {t("common:localAgent.run")}
          </Button>
        )}
        <Button size="icon" variant="outline" aria-label={t("common:actions.copy")} onClick={() => { navigator.clipboard.writeText(value); toast.success(t("common:actions.copied")); }}><Copy className="h-4 w-4" /></Button>
      </div>
      {progress && (
        <p className="flex items-center gap-1 text-xs text-muted">
          <Check className="h-3 w-3 text-success" aria-hidden />
          {progress}
        </p>
      )}
      {hint && <p className="text-xs text-muted">{hint}</p>}
    </div>
  );
}
