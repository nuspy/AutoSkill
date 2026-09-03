import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { useReviewActions, useReviewBundle } from "@/api/hooks/review";
import { useVersionFile } from "@/api/hooks/versions";
import { useSession } from "@/stores/session";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Textarea } from "@/components/ui/input";
import { Markdown } from "@/components/ui/markdown";
import { Badge, ErrorState, PageHeader, Skeleton } from "@/components/ui/misc";
import { DiffView } from "./DiffView";
import { errorMessage } from "@/lib/errors";
import { cn } from "@/lib/cn";

export default function ReviewPage() {
  const { requestId = "" } = useParams();
  const { t } = useTranslation(["skills", "common"]);
  const user = useSession((s) => s.user);
  const bundle = useReviewBundle(requestId);
  const actions = useReviewActions(requestId);
  const [tab, setTab] = useState<"diff" | "skill" | "checklist">("diff");
  const [comment, setComment] = useState("");
  const skillMd = useVersionFile(bundle.data?.version_id ?? "", tab === "skill" ? "SKILL.md" : null);
  if (bundle.isLoading || !bundle.data) return <Skeleton className="h-64" />;
  const b = bundle.data;
  const isReviewer = user?.role === "admin" || user?.role === "reviewer";
  const open = b.request.state === "open" || b.request.state === "in_review";
  const decide = (decision: string) => actions.decide.mutate({ decision, comment: comment || undefined }, { onSuccess: () => toast.success(t("skills:review.decided")), onError: (e) => toast.error(errorMessage(e, t)) });
  const checklist = b.request.checklist as Record<string, unknown>;
  return (
    <>
      <PageHeader title={`${b.skill_title} · v${b.version}`} subtitle={b.request.summary ?? undefined} actions={
        <div className="flex gap-2">
          <Badge tone={b.request.state === "decided" ? "success" : "warning"}>{t(`skills:review.state.${b.request.state}`)}</Badge>
          {isReviewer && open && !b.request.assignee_id && <Button size="sm" variant="outline" onClick={() => actions.assign.mutate()}>{t("skills:review.assignMe")}</Button>}
          {open && b.request.requested_by === user?.id && <Button size="sm" variant="ghost" onClick={() => actions.withdraw.mutate()}>{t("skills:review.withdraw")}</Button>}
          <Link className="text-sm text-primary hover:underline" to={`/p/${b.request.project_id}/skills/${b.request.skill_id}/versions`}>{t("skills:tabs.versions")}</Link>
        </div>
      } />
      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <Card>
          <div className="flex gap-1 border-b border-border px-5">
            {(["diff", "skill", "checklist"] as const).map((k) => <button key={k} className={cn("border-b-2 px-3 py-2 text-sm font-medium", tab === k ? "border-primary text-primary" : "border-transparent text-muted")} onClick={() => setTab(k)}>{t(`skills:review.tabs.${k}`)}</button>)}
          </div>
          <CardBody>
            {tab === "diff" && <DiffView diff={b.diff} />}
            {tab === "skill" && (skillMd.data ? <Markdown source={skillMd.data.content} /> : <Skeleton className="h-40" />)}
            {tab === "checklist" && (
              <ul className="space-y-1 text-sm">
                {Object.entries(checklist).map(([k, v]) => (
                  <li key={k} className="flex items-center gap-2"><Badge tone={v === true ? "success" : v === false ? "danger" : "neutral"}>{v === true ? "✓" : v === false ? "✕" : Array.isArray(v) ? v.length : String(v)}</Badge><span>{t(`skills:review.checklist.${k}`, { defaultValue: k })}</span>{Array.isArray(v) && v.length > 0 && <span className="text-xs text-muted">{v.join(", ")}</span>}</li>
                ))}
                <li className="text-xs text-muted">{t("skills:review.memoryCount", { count: b.memory_count })}</li>
              </ul>
            )}
          </CardBody>
        </Card>
        <div className="space-y-4">
          {isReviewer && open && (
            <Card>
              <CardHeader title={t("skills:review.decision")} />
              <CardBody className="space-y-3">
                <Field label={t("skills:review.comment")}><Textarea rows={4} value={comment} onChange={(e) => setComment(e.target.value)} /></Field>
                <div className="flex flex-col gap-2">
                  <Button loading={actions.decide.isPending} onClick={() => decide("approved")}>{t("skills:review.decisions.approved")}</Button>
                  <Button variant="outline" onClick={() => decide("changes_requested")}>{t("skills:review.decisions.changes_requested")}</Button>
                  <Button variant="ghost" className="text-danger" onClick={() => decide("rejected")}>{t("skills:review.decisions.rejected")}</Button>
                </div>
                {actions.decide.isError && <ErrorState message={errorMessage(actions.decide.error, t)} />}
              </CardBody>
            </Card>
          )}
          {b.decisions.length > 0 && (
            <Card>
              <CardHeader title={t("skills:review.history")} />
              <ul className="divide-y divide-border">
                {b.decisions.map((d) => <li key={d.id} className="px-5 py-2 text-sm"><Badge tone={d.decision === "approved" ? "success" : d.decision === "rejected" ? "danger" : "warning"}>{t(`skills:review.decisions.${d.decision}`)}</Badge>{d.comment && <p className="mt-1 text-muted">{d.comment}</p>}</li>)}
              </ul>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
