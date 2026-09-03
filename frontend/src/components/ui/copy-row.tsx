import { useTranslation } from "react-i18next";
import { Copy } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";

/** A label, a monospace value and a copy button: used for commands and online addresses. */
export function CopyRow({ label, value, hint }: { label: string; value: string; hint?: string }) {
  const { t } = useTranslation(["common"]);
  return (
    <div className="space-y-1">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</p>
      <div className="flex items-start gap-2">
        <pre className="flex-1 overflow-x-auto whitespace-pre-wrap break-all rounded-lg bg-accent p-3 font-mono text-xs">{value}</pre>
        <Button size="icon" variant="outline" aria-label={t("common:actions.copy")} onClick={() => { navigator.clipboard.writeText(value); toast.success(t("common:actions.copied")); }}><Copy className="h-4 w-4" /></Button>
      </div>
      {hint && <p className="text-xs text-muted">{hint}</p>}
    </div>
  );
}
