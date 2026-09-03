import { useTranslation } from "react-i18next";
import type { VersionDiff } from "@/api/types";
import { Badge } from "@/components/ui/misc";
import { cn } from "@/lib/cn";

export function DiffView({ diff }: { diff: VersionDiff }) {
  const { t } = useTranslation(["skills"]);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted">{diff.from ? `v${diff.from} → v${diff.to}` : `v${diff.to} (${t("skills:review.firstVersion")})`}</span>
        <Badge tone="primary">{t("skills:review.suggestedBump", { bump: diff.suggested_bump })}</Badge>
        {diff.steps.added.length > 0 && <Badge tone="success">+{diff.steps.added.length} {t("skills:review.stepsAdded")}</Badge>}
        {diff.steps.changed.length > 0 && <Badge tone="warning">{diff.steps.changed.length} {t("skills:review.stepsChanged")}</Badge>}
        {diff.steps.removed.length > 0 && <Badge tone="danger">-{diff.steps.removed.length} {t("skills:review.stepsRemoved")}</Badge>}
      </div>
      {diff.files.length === 0 && <p className="text-sm text-muted">{t("skills:review.noChanges")}</p>}
      {diff.files.map((f) => (
        <div key={f.path} className="rounded-lg border border-border">
          <div className="flex items-center gap-2 border-b border-border px-3 py-1.5 text-sm"><code>{f.path}</code><Badge tone={f.status === "added" ? "success" : f.status === "removed" ? "danger" : "warning"}>{f.status}</Badge></div>
          {f.diff ? (
            <pre className="max-h-96 overflow-auto p-3 text-xs leading-5">
              {f.diff.split("\n").map((line, i) => (
                <div key={i} className={cn(line.startsWith("+") && !line.startsWith("+++") && "bg-success/10", line.startsWith("-") && !line.startsWith("---") && "bg-danger/10", line.startsWith("@@") && "text-primary")}>{line || " "}</div>
              ))}
            </pre>
          ) : <p className="p-3 text-xs text-muted">binary</p>}
        </div>
      ))}
    </div>
  );
}
