import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/client";
import { useVersions } from "@/api/hooks/versions";
import type { ImprovementProposal } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Select, Textarea } from "@/components/ui/input";
import { Badge, EmptyState, ErrorState, Skeleton } from "@/components/ui/misc";
import { errorMessage } from "@/lib/errors";
import { timeAgo } from "@/lib/format";
import { cn } from "@/lib/cn";

const TONE: Record<string, "neutral" | "primary" | "success" | "warning" | "danger"> = { analyzing: "primary", proposed: "warning", under_review: "warning", accepted: "success", rejected: "neutral", failed: "danger", superseded: "neutral" };

export default function ImprovementsTab() {
  const { projectId = "", skillId = "" } = useParams();
  const { t, i18n } = useTranslation(["skills", "common"]);
  const qc = useQueryClient();
  const versions = useVersions(skillId);
  const proposals = useQuery({ queryKey: ["skills", skillId, "improvements"], queryFn: () => api<ImprovementProposal[]>(`/skills/${skillId}/improvements`), refetchInterval: (q) => (q.state.data?.some((p) => p.state === "analyzing") ? 3000 : false) });
  const [base, setBase] = useState("");
  const baseId = base || versions.data?.find((v) => ["published", "tested", "testing"].includes(v.state))?.id || versions.data?.[0]?.id || "";
  const analysis = useQuery({ queryKey: ["skills", skillId, "analysis", baseId], queryFn: () => api<ImprovementProposal["analysis"] & { source_run_ids: string[] }>(`/skills/${skillId}/improvements/analysis?version_id=${baseId}`), enabled: !!baseId });
  const propose = useMutation({ mutationFn: () => api<ImprovementProposal>(`/skills/${skillId}/improvements`, { method: "POST", body: { base_version_id: baseId } }), onSuccess: () => { toast.success(t("skills:improvements.started")); qc.invalidateQueries({ queryKey: ["skills", skillId, "improvements"] }); } });
  const decide = useMutation({ mutationFn: ({ id, accept, comment }: { id: string; accept: boolean; comment?: string }) => api<ImprovementProposal>(`/improvements/${id}/decision`, { method: "POST", body: { accept, comment } }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["skills", skillId] }); toast.success(t("skills:improvements.decided")); } });
  const [comment, setComment] = useState("");
  const a = analysis.data;
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title={t("skills:improvements.title")} description={t("skills:improvements.subtitle")} actions={
          <div className="flex items-end gap-2">
            <Select className="w-36" value={baseId} onChange={(e) => setBase(e.target.value)}>{versions.data?.map((v) => <option key={v.id} value={v.id}>v{v.version} · {t(`skills:versions.state.${v.state}`)}</option>)}</Select>
            <Button disabled={!baseId} loading={propose.isPending} onClick={() => propose.mutate(undefined, { onError: (e) => toast.error(errorMessage(e, t)) })}><Sparkles className="h-4 w-4" />{t("skills:improvements.propose")}</Button>
          </div>
        } />
        <CardBody>
          {a ? (
            <div className="grid gap-3 text-sm sm:grid-cols-4">
              <Stat label={t("skills:improvements.runs")} value={String(a.runs_total ?? 0)} />
              <Stat label={t("skills:improvements.failed")} value={String(a.runs_failed ?? 0)} tone={(a.runs_failed ?? 0) >= 3 ? "danger" : "neutral"} />
              <Stat label={t("skills:improvements.issues")} value={String(a.issues ?? 0)} />
              <Stat label={t("skills:improvements.corrections")} value={String(a.corrections ?? 0)} />
              {a.clusters && a.clusters.length > 0 && (
                <ul className="sm:col-span-4 space-y-1">
                  {a.clusters.slice(0, 5).map((c, i) => <li key={i} className="flex items-center gap-2"><Badge tone="warning">×{c.count}</Badge><code className="text-xs">{c.step_key}</code><span className="text-muted">{c.step_title}</span><span className="truncate text-xs text-muted">{c.signature}</span></li>)}
                </ul>
              )}
              {(!a.clusters || a.clusters.length === 0) && <p className="sm:col-span-4 text-muted">{t("skills:improvements.nothing")}</p>}
            </div>
          ) : <Skeleton className="h-16" />}
        </CardBody>
      </Card>
      {proposals.data && proposals.data.length === 0 && <EmptyState title={t("skills:improvements.none")} description={t("skills:improvements.noneHelp")} />}
      {proposals.data?.map((p) => (
        <Card key={p.id} className={cn(p.state === "proposed" || p.state === "under_review" ? "border-warning/60" : "")}>
          <CardHeader title={<span className="flex items-center gap-2"><Badge tone={TONE[p.state] ?? "neutral"}>{t(`skills:improvements.state.${p.state}`)}</Badge><span>{t(`skills:improvements.trigger.${p.trigger}`)}</span></span>} description={`${timeAgo(p.created_at, i18n.language)}${p.golden_pass_rate != null ? ` · ${t("skills:improvements.goldenCoverage", { pct: Math.round(p.golden_pass_rate * 100) })}` : ""}`} actions={p.proposed_version_id ? <Link className="text-sm text-primary hover:underline" to={`/p/${projectId}/skills/${skillId}/versions`}>{t("skills:tabs.versions")}</Link> : undefined} />
          <CardBody className="space-y-3 text-sm">
            {p.error && <ErrorState message={p.error} />}
            {p.analysis.hypotheses && <ul className="list-disc pl-5">{p.analysis.hypotheses.map((h, i) => <li key={i}>{h}</li>)}</ul>}
            {p.rationale && <p className="rounded-lg bg-accent p-3">{p.rationale}</p>}
            {p.diff_summary.steps && <p className="text-xs text-muted">{t("skills:improvements.stepsChanged")}: {p.diff_summary.steps.changed.join(", ") || "—"} · {t("skills:review.suggestedBump", { bump: p.diff_summary.suggested_bump })}</p>}
            {(p.state === "proposed" || p.state === "under_review") && (
              <div className="space-y-2">
                <p className="text-xs text-muted">{t("skills:improvements.decideHelp")}</p>
                <Field label={t("skills:review.comment")}><Textarea rows={2} value={comment} onChange={(e) => setComment(e.target.value)} /></Field>
                <div className="flex gap-2">
                  <Button loading={decide.isPending} onClick={() => decide.mutate({ id: p.id, accept: true, comment: comment || undefined }, { onError: (e) => toast.error(errorMessage(e, t)) })}>{t("skills:improvements.accept")}</Button>
                  <Button variant="outline" onClick={() => decide.mutate({ id: p.id, accept: false, comment: comment || undefined }, { onError: (e) => toast.error(errorMessage(e, t)) })}>{t("skills:improvements.reject")}</Button>
                </div>
              </div>
            )}
            {p.decision_comment && <p className="text-xs text-muted">{p.decision_comment}</p>}
          </CardBody>
        </Card>
      ))}
    </div>
  );
}

function Stat({ label, value, tone = "neutral" }: { label: string; value: string; tone?: "neutral" | "danger" }) {
  return <div className="rounded-lg border border-border p-3"><p className="text-xs uppercase tracking-wide text-muted">{label}</p><p className={cn("text-xl font-semibold", tone === "danger" && "text-danger")}>{value}</p></div>;
}
