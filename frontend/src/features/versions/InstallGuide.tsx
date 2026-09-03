import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Copy } from "lucide-react";
import { toast } from "sonner";
import { useInstallDoc, useTargets } from "@/api/hooks/versions";
import { Button } from "@/components/ui/button";
import { Markdown } from "@/components/ui/markdown";
import { Skeleton } from "@/components/ui/misc";
import { cn } from "@/lib/cn";

export function InstallGuide({ versionId, trial = false }: { versionId: string; trial?: boolean }) {
  const { t } = useTranslation(["skills", "common"]);
  const targets = useTargets();
  const [target, setTarget] = useState("hermes");
  const doc = useInstallDoc(versionId, target, trial);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1">
        {targets.data?.map((tg) => (
          <button key={tg.id} className={cn("rounded-full border px-3 py-1 text-sm", target === tg.id ? "border-primary bg-primary/10 text-primary" : "border-border hover:bg-accent")} onClick={() => setTarget(tg.id)}>{tg.display_name}</button>
        ))}
        <Button size="sm" variant="ghost" className="ml-auto" disabled={!doc.data} onClick={() => { navigator.clipboard.writeText(doc.data?.markdown ?? ""); toast.success(t("common:actions.copied")); }}><Copy className="h-3.5 w-3.5" />{t("common:actions.copy")}</Button>
      </div>
      {doc.data ? <Markdown source={doc.data.markdown} /> : <Skeleton className="h-48" />}
    </div>
  );
}
