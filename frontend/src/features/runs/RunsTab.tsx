import { useState } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useRun, useRunFeedback, useRuns } from "@/api/hooks/trials";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge, EmptyState, Skeleton } from "@/components/ui/misc";
import { ChevronRight } from "lucide-react";
import type { RunStep } from "@/api/types";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/cn";

const TONE: Record<string, "neutral" | "primary" | "success" | "warning" | "danger"> = { running: "primary", succeeded: "success", failed: "danger", aborted: "warning", needs_review: "warning" };

/** An action recorded by the agent. Usually a small object ({"file": "...", "sheet": "..."}), so
 *  it reads better as label/value pairs than as raw JSON; anything else falls back to JSON. */
function ActionView({ value }: { value: unknown }) {
  if (value == null) return null;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return <p className="break-words">{String(value)}</p>;
  }
  if (typeof value === "object" && !Array.isArray(value)) {
    const entries = Object.entries(value as Record<string, unknown>);
    const flat = entries.every(([, v]) => v == null || typeof v !== "object");
    if (flat && entries.length > 0) {
      return (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
          {entries.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-muted">{k}</dt>
              <dd className="break-all">{v == null ? "—" : String(v)}</dd>
            </div>
          ))}
        </dl>
      );
    }
  }
  return <pre className="overflow-x-auto rounded bg-accent p-2">{JSON.stringify(value, null, 2)}</pre>;
}

function Field({ label, value, tone }: { label: string; value: unknown; tone?: "danger" }) {
  if (value == null) return null;
  return (
    <div>
      <h5 className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</h5>
      <div className={cn("mt-0.5 text-xs", tone === "danger" && "text-danger")}>
        <ActionView value={value} />
      </div>
    </div>
  );
}

function RunStepItem({ step: s }: { step: RunStep }) {
  const { t } = useTranslation(["skills"]);
  const [open, setOpen] = useState(false);
  return (
    <li className="rounded-lg border border-border text-sm">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex w-full items-center gap-2 p-2 text-left min-h-11">
        <ChevronRight className={cn("h-4 w-4 shrink-0 text-muted transition-transform", open && "rotate-90")} aria-hidden />
        <Badge tone={TONE[s.status] ?? "neutral"}>{s.status}</Badge>
        <span className="font-medium">{s.title ?? s.step_key}</span>
        <code className="text-xs text-muted">{s.step_key}</code>
        {s.duration_ms != null && <span className="ml-auto shrink-0 text-xs text-muted">{s.duration_ms} ms</span>}
      </button>
      {open && (
        <div className="space-y-2 border-t border-border px-3 py-2">
          <Field label={t("skills:runs.executedAction")} value={s.executed_action} />
          {/* shown only when it differs: otherwise it is noise next to what was actually done */}
          {JSON.stringify(s.proposed_action) !== JSON.stringify(s.executed_action) && (
            <Field label={t("skills:runs.proposedAction")} value={s.proposed_action} />
          )}
          <Field label={t("skills:runs.tool")} value={s.tool_name} />
          <Field label={t("skills:runs.inputs")} value={s.inputs} />
          <Field label={t("skills:runs.outputs")} value={s.outputs} />
          <Field label={t("skills:runs.error")} value={s.error} tone="danger" />
          {s.executed_action == null && s.outputs == null && s.error == null && (
            <p className="text-xs text-muted">{t("skills:runs.noDetail")}</p>
          )}
        </div>
      )}
    </li>
  );
}

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
          {steps.map((s) => <RunStepItem key={s.id} step={s} />)}
        </ol>
        {annotations.length > 0 && (
          <ul className="space-y-1 text-sm">{annotations.map((a) => <li key={a.id}><Badge tone={a.kind === "issue" ? "danger" : "neutral"}>{a.kind}{a.severity ? ` · ${a.severity}` : ""}</Badge> {a.text}</li>)}</ul>
        )}
      </CardBody>
    </Card>
  );
}
