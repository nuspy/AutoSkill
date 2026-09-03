import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Wrench } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/client";
import type { McpVersion, StepDefinition } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Badge, EmptyState, ErrorState, Skeleton } from "@/components/ui/misc";
import { errorMessage } from "@/lib/errors";
import { cn } from "@/lib/cn";

export function McpTab({ versionId, steps, skillName }: { versionId: string; steps: StepDefinition[]; skillName: string }) {
  const { t } = useTranslation(["skills", "common"]);
  const qc = useQueryClient();
  const mcp = useQuery({ queryKey: ["versions", versionId, "mcp"], queryFn: () => api<McpVersion | null>(`/versions/${versionId}/mcp`), refetchInterval: (q) => (q.state.data === null ? 4000 : false) });
  const generate = useMutation({ mutationFn: () => api<{ job_id: string }>(`/versions/${versionId}/mcp/generate`, { method: "POST" }), onSuccess: () => { toast.success(t("skills:mcp.generating")); setTimeout(() => { qc.invalidateQueries({ queryKey: ["versions", versionId] }); }, 2500); } });
  const [file, setFile] = useState<string | null>(null);
  const content = useQuery({ queryKey: ["versions", versionId, "mcp", "file", file], queryFn: () => api<{ content: string }>(`/versions/${versionId}/mcp/files/${file}`), enabled: !!file });
  const deterministic = steps.filter((s) => s.kind === "deterministic");
  if (mcp.isLoading) return <Skeleton className="h-32" />;
  const mv = mcp.data;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <p className="flex-1 text-sm text-muted">{t("skills:mcp.help", { count: deterministic.length })}</p>
        <Button disabled={deterministic.length === 0} loading={generate.isPending} onClick={() => generate.mutate(undefined, { onError: (e) => toast.error(errorMessage(e, t)) })}><Wrench className="h-4 w-4" />{mv ? t("skills:mcp.regenerate") : t("skills:mcp.generate")}</Button>
      </div>
      {!mv && <EmptyState title={t("skills:mcp.none")} description={deterministic.length ? t("skills:mcp.noneHelp") : t("skills:mcp.noDeterministic")} />}
      {mv && (
        <>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <code className="rounded bg-accent px-1.5 py-0.5">{mv.server_name}</code>
            <Badge tone={mv.state === "trial_passed" ? "success" : mv.state === "trial_failed" ? "danger" : "primary"}>{t(`skills:mcp.state.${mv.state}`, { defaultValue: mv.state })}</Badge>
            <Badge>{t("skills:mcp.build", { n: mv.build })}</Badge>
            {mv.dependencies.length > 0 && <span className="text-xs text-muted">{t("skills:mcp.deps")}: {mv.dependencies.join(", ")}</span>}
          </div>
          <ul className="space-y-2">
            {mv.tools.map((tool) => (
              <li key={tool.name} className="rounded-lg border border-border p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2"><code className="font-semibold">{tool.name}</code><Badge>{tool.step_key}</Badge><Badge tone={tool.side_effects === "irreversible" ? "danger" : tool.side_effects === "reversible" ? "warning" : "success"}>{t(`skills:knowledge.sideEffects.${tool.side_effects}`)}</Badge>{tool.network && <Badge tone="neutral">network</Badge>}</div>
                <p className="mt-1 text-muted">{tool.description}</p>
                <p className="mt-1 text-xs text-muted">{Object.keys((tool.input_schema.properties as Record<string, unknown>) ?? {}).join(", ")}</p>
              </li>
            ))}
          </ul>
          {mv.env_requirements.length > 0 && <p className="text-sm text-muted">{t("skills:mcp.env")}: {mv.env_requirements.map((e) => <code key={e.name} className="mr-1 rounded bg-accent px-1">{e.name}</code>)}</p>}
          <div className="rounded-lg border border-border p-3 text-sm">
            <p className="font-medium">{t("skills:mcp.check")}</p>
            <p className="text-muted">{t("skills:mcp.checkHelp")}</p>
            <pre className="mt-2 overflow-x-auto rounded bg-accent p-2 font-mono text-xs">{`autoskill mcp check ./${skillName} --report ${mv.id}`}</pre>
            {mv.trial_report && (mv.trial_report.ok && !(mv.trial_report.missing_tools?.length) ? <p className="mt-2 text-success">{t("skills:mcp.checkOk", { count: mv.trial_report.tools.length })}</p> : <ErrorState message={mv.trial_report.error ?? t("skills:mcp.checkMissing", { tools: (mv.trial_report.missing_tools ?? []).join(", ") })} />)}
          </div>
          <details className="text-sm"><summary className="cursor-pointer text-muted">{t("skills:mcp.buildLog")}</summary><pre className="mt-2 rounded bg-accent p-2 text-xs">{mv.build_log}</pre>{mv.static_report.issues.length > 0 && <ul className="mt-2 text-xs">{mv.static_report.issues.map((i, k) => <li key={k} className={cn(i.level === "error" ? "text-danger" : "text-warning")}>{i.message}</li>)}</ul>}</details>
          <div className="grid gap-3 md:grid-cols-[220px_1fr]">
            <ul className="space-y-1 text-xs">{mv.manifest.files.map((f) => <li key={f.path}><button className={cn("w-full truncate rounded px-2 py-1 text-left", file === f.path ? "bg-primary/10 text-primary" : "hover:bg-accent")} onClick={() => setFile(f.path)}>{f.path}</button></li>)}</ul>
            <div className="min-w-0">{file && (content.data ? <pre className="max-h-96 overflow-auto rounded bg-accent p-3 text-xs">{content.data.content}</pre> : <Skeleton className="h-40" />)}</div>
          </div>
        </>
      )}
    </div>
  );
}
