import { useState } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useRun, useRunFeedback, useRuns } from "@/api/hooks/trials";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge, EmptyState, Skeleton } from "@/components/ui/misc";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/cn";

const TONE: Record<string, "neutral" | "primary" | "success" | "warning" | "danger"> = { running: "primary", succeeded: "success", failed: "danger", aborted: "warning", needs_review: "warning" };

export default function RunsTab({ projectId: pid, skillId: sid }: { projectId?: string; skillId?: string }) {
  const params = useParams();
  const projectId = pid ?? params.projectId ?? "";
  const skillId = sid ?? params.skillId;
  const { t, i18n } = useTranslation(["skills", "common"]);
  const runs = useRuns(projectId, skillId);
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
      <Card>
        <CardHeader title={t("skills:runs.title")} />
        {runs.isLoading && <CardBody><Skeleton className="h-20" /></CardBody>}
        {runs.data && runs.data.length === 0 && <CardBody><EmptyState title={t("skills:runs.none")} /></CardBody>}
        <ul className="divide-y divide-border">
          {runs.data?.map((r) => (
            <li key={r.id}>
              <button className={cn("flex w-full items-center gap-2 px-4 py-2 text-left text-sm", selected === r.id ? "bg-primary/5" : "hover:bg-accent")} onClick={() => setSelected(r.id)}>
                <Badge tone={TONE[r.status] ?? "neutral"}>{t(`skills:runs.status.${r.status}`)}</Badge>
                <span className="flex-1 truncate text-muted">{r.source} · v{r.skill_version ?? "?"} · {r.agent_target ?? ""}</span>
                {r.is_golden && <Badge tone="primary">★</Badge>}
                <span className="text-xs text-muted">{formatDate(r.started_at, i18n.language)}</span>
              </button>
            </li>
          ))}
        </ul>
      </Card>
      {selected ? <RunDetail runId={selected} /> : <EmptyState title={t("skills:runs.select")} />}
    </div>
  );
}

function RunDetail({ runId }: { runId: string }) {
  const { t } = useTranslation(["skills", "common"]);
  const run = useRun(runId);
  const feedback = useRunFeedback(runId);
  if (run.isLoading || !run.data) return <Skeleton className="h-40" />;
  const { run: r, steps, annotations } = run.data;
  return (
    <Card>
      <CardHeader title={`${t("skills:runs.run")} · ${t(`skills:runs.status.${r.status}`)}`} description={r.summary ?? r.inputs_summary ?? undefined} actions={
        <div className="flex gap-2">
          <Button size="sm" variant={r.is_golden ? "primary" : "outline"} onClick={() => feedback.mutate({ is_golden: !r.is_golden })}>{r.is_golden ? t("skills:runs.golden") : t("skills:runs.markGolden")}</Button>
          {(["ok", "corrected", "wrong"] as const).map((f) => <Button key={f} size="sm" variant={r.human_feedback === f ? "secondary" : "ghost"} onClick={() => feedback.mutate({ human_feedback: f })}>{t(`skills:runs.feedback.${f}`)}</Button>)}
        </div>
      } />
      <CardBody className="space-y-3">
        {r.error && <pre className="overflow-x-auto rounded-lg bg-danger/10 p-2 text-xs">{JSON.stringify(r.error, null, 2)}</pre>}
        {steps.length === 0 && <p className="text-sm text-muted">{t("skills:runs.noSteps")}</p>}
        <ol className="space-y-2">
          {steps.map((s) => (
            <li key={s.id} className="rounded-lg border border-border p-2 text-sm">
              <div className="flex items-center gap-2"><Badge tone={TONE[s.status] ?? "neutral"}>{s.status}</Badge><span className="font-medium">{s.title ?? s.step_key}</span><code className="text-xs text-muted">{s.step_key}</code>{s.duration_ms != null && <span className="ml-auto text-xs text-muted">{s.duration_ms} ms</span>}</div>
              {s.outputs != null && <pre className="mt-1 overflow-x-auto rounded bg-accent p-2 text-xs">{JSON.stringify(s.outputs, null, 2)}</pre>}
              {s.error != null && <pre className="mt-1 overflow-x-auto rounded bg-danger/10 p-2 text-xs">{JSON.stringify(s.error, null, 2)}</pre>}
            </li>
          ))}
        </ol>
        {annotations.length > 0 && (
          <ul className="space-y-1 text-sm">{annotations.map((a) => <li key={a.id}><Badge tone={a.kind === "issue" ? "danger" : "neutral"}>{a.kind}{a.severity ? ` · ${a.severity}` : ""}</Badge> {a.text}</li>)}</ul>
        )}
      </CardBody>
    </Card>
  );
}
