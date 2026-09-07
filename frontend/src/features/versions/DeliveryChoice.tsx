import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, FileCode2, Wrench } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/client";
import type { DeliveryAnalysis } from "@/api/types";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge, ErrorState, Skeleton } from "@/components/ui/misc";
import { errorMessage } from "@/lib/errors";
import { cn } from "@/lib/cn";

/** How the deterministic steps will be written: scripts (the default) or tools of an MCP server.
 *  The choice is per skill; steps that cannot be scripts are listed with the reason. */
export function DeliveryChoice({ versionId }: { versionId: string }) {
  const { t } = useTranslation(["skills", "common"]);
  const qc = useQueryClient();
  const key = ["versions", versionId, "delivery"];
  const analysis = useQuery({ queryKey: key, queryFn: () => api<DeliveryAnalysis>(`/versions/${versionId}/delivery`) });
  const choose = useMutation({
    mutationFn: (delivery: "script" | "mcp") => api<DeliveryAnalysis>(`/versions/${versionId}/delivery`, { method: "PUT", body: { delivery } }),
    onSuccess: (data) => {
      qc.setQueryData(key, data);
      toast.success(t("common:status.saved"));
    },
    onError: (e) => toast.error(errorMessage(e, t)),
  });

  if (analysis.isLoading || !analysis.data) return <Skeleton className="h-32" />;
  const d = analysis.data;
  const blocked = d.steps.filter((s) => s.needs_mcp);

  const option = (value: "script" | "mcp", icon: React.ReactNode, disabled: boolean) => (
    <button
      type="button"
      onClick={() => !disabled && choose.mutate(value)}
      disabled={disabled || choose.isPending}
      aria-pressed={d.delivery === value}
      className={cn(
        "flex flex-1 items-start gap-3 rounded-xl border p-3 text-left min-h-11",
        d.delivery === value ? "border-primary bg-primary/5" : "border-border",
        disabled && "cursor-not-allowed opacity-50",
      )}
    >
      <span className="mt-0.5 shrink-0 text-muted">{icon}</span>
      <span>
        <span className="flex items-center gap-2 font-medium">
          {t(`skills:delivery.${value}`)}
          {value === "script" && <Badge tone="neutral">{t("skills:delivery.default")}</Badge>}
        </span>
        <span className="mt-0.5 block text-xs text-muted">{t(`skills:delivery.${value}Help`)}</span>
      </span>
    </button>
  );

  return (
    <Card>
      <CardHeader title={t("skills:delivery.title")} description={t("skills:delivery.description")} />
      <CardBody className="space-y-3">
        <div className="flex flex-col gap-2 sm:flex-row">
          {option("script", <FileCode2 className="h-5 w-5" />, d.forced)}
          {option("mcp", <Wrench className="h-5 w-5" />, false)}
        </div>
        {blocked.length > 0 && (
          <div className="rounded-xl border border-warning/40 bg-warning/5 p-3 text-sm">
            <p className="flex items-center gap-2 font-medium">
              <AlertTriangle className="h-4 w-4 text-warning" aria-hidden />
              {t("skills:delivery.forced", { count: blocked.length })}
            </p>
            <ul className="mt-2 space-y-1 text-xs">
              {blocked.map((s) => (
                <li key={s.key}>
                  <code className="rounded bg-accent px-1 py-0.5">{s.key}</code>{" "}
                  {s.reasons.map((r) => t(`skills:delivery.reason.${r}`, { defaultValue: r })).join(" · ")}
                </li>
              ))}
            </ul>
          </div>
        )}
        {d.agents_without_shell.length > 0 && (
          <p className="text-xs text-muted">{t("skills:delivery.noShell", { agents: d.agents_without_shell.join(", ") })}</p>
        )}
        {choose.isError && <ErrorState message={errorMessage(choose.error, t)} />}
      </CardBody>
    </Card>
  );
}
