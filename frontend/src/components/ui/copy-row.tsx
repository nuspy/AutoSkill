import { useTranslation } from "react-i18next";
import { Copy } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";

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

/** A label, a monospace value and a copy button: used for commands and online addresses. */
export function CopyRow({ label, value, hint }: { label?: string; value: string; hint?: string }) {
  const { t } = useTranslation(["common"]);
  return (
    <div className="space-y-1">
      {label && <p className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</p>}
      <div className="flex items-start gap-2">
        <pre className="flex-1 overflow-x-auto whitespace-pre-wrap break-all rounded-lg bg-accent p-3 font-mono text-xs">{value}</pre>
        <Button size="icon" variant="outline" aria-label={t("common:actions.copy")} onClick={() => { navigator.clipboard.writeText(value); toast.success(t("common:actions.copied")); }}><Copy className="h-4 w-4" /></Button>
      </div>
      {hint && <p className="text-xs text-muted">{hint}</p>}
    </div>
  );
}
