import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AlertTriangle, Archive, Check, MessageSquare, PauseCircle, PlayCircle, RotateCcw, SkipForward, Square, Undo2 } from "lucide-react";
import { toast } from "sonner";
import { useTrial, useTrialActions } from "@/api/hooks/trials";
import type { Checkpoint, Discussion, StepDefinition, TrialSnapshot } from "@/api/types";
import { Button } from "@/components/ui/button";
import { CopyRow } from "@/components/ui/copy-row";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Textarea } from "@/components/ui/input";
import { Markdown } from "@/components/ui/markdown";
import { Badge, EmptyState, ErrorState, Skeleton, Spinner } from "@/components/ui/misc";
import { InstallGuide } from "@/features/versions/InstallGuide";
import { errorMessage } from "@/lib/errors";
import { timeAgo } from "@/lib/format";
import { cn } from "@/lib/cn";

const LIVE = new Set(["requested", "installing", "installed", "testing"]);

export default function TrialPage() {
  const { trialId = "", projectId = "", skillId = "" } = useParams();
  const { t, i18n } = useTranslation(["skills", "common"]);
  const [live, setLive] = useState(true);
  const trial = useTrial(trialId, live);
  const state = trial.data?.trial.state;
  useEffect(() => setLive(!!state && LIVE.has(state)), [state]);
  const actions = useTrialActions(trialId);
  if (trial.isLoading || !trial.data) return <Skeleton className="h-64" />;
  const d = trial.data;
  const tr = d.trial;
  const done = ["decided", "removed", "abandoned"].includes(tr.state);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Link className="text-primary hover:underline" to={`/p/${projectId}/skills/${skillId}/versions`}>{d.skill_title} v{d.version}</Link>
        <Badge tone={tr.state === "testing" ? "primary" : tr.state === "suspended" ? "warning" : done ? (tr.outcome === "accepted" ? "success" : "neutral") : "neutral"}>{t(`skills:trials.state.${tr.state}`)}</Badge>
        <Badge>{tr.target_agent}</Badge>
        <Badge>{t(`skills:trials.modes.${tr.mode}`)}</Badge>
        {tr.outcome && <Badge tone="success">{t(`skills:trials.outcomes.${tr.outcome}`)}</Badge>}
        <span className="ml-auto text-xs text-muted">{timeAgo(tr.updated_at, i18n.language)}</span>
        {tr.state === "testing" || tr.state === "installed" ? <Button size="sm" variant="outline" onClick={() => actions.suspend.mutate()}><PauseCircle className="h-4 w-4" />{t("skills:trials.suspend")}</Button> : null}
        {tr.state === "suspended" ? <Button size="sm" variant="outline" onClick={() => actions.resume.mutate()}><PlayCircle className="h-4 w-4" />{t("skills:trials.resume")}</Button> : null}
        {!done && tr.mode === "interactive" && (
          <label className="flex items-center gap-1 text-xs text-muted" title={t("skills:trials.autoConfirmHint")}><input type="checkbox" checked={tr.auto_confirm} onChange={(e) => actions.patch.mutate({ auto_confirm: e.target.checked })} />{t("skills:trials.autoConfirmShort")}</label>
        )}
      </div>
      {tr.state === "suspended" && <div className="rounded-lg border border-warning/40 bg-warning/10 px-4 py-2 text-sm">{t("skills:trials.suspendedBanner")}</div>}
      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <div className="space-y-4">
          {tr.state === "requested" && (
            <Card>
              <CardHeader title={t("skills:trials.waitingInstall")} description={t("skills:trials.waitingInstallHelp")} />
              <CardBody className="space-y-4">
                {d.bundle_url && (
                  <div className="space-y-3 rounded-lg border border-border p-3">
                    <CopyRow label={t("skills:trials.bundleUrl")} value={d.bundle_url} hint={t("skills:trials.bundleUrlHint")} />
                    {d.manifest_url && <CopyRow label={t("skills:trials.manifestUrl")} value={d.manifest_url} />}
                    <CopyRow label={t("skills:trials.tellAgent")} value={t("skills:trials.tellAgentText", { url: d.bundle_url, manifest: d.manifest_url ?? "" })} />
                  </div>
                )}
                <InstallGuide versionId={tr.skill_version_id} trial />
              </CardBody>
            </Card>
          )}
          {!done && tr.state !== "requested" && d.bundle_url && (
            <details className="rounded-lg border border-border p-3 text-sm">
              <summary className="cursor-pointer font-medium">{t("skills:trials.bundleUrl")}</summary>
              <div className="mt-3 space-y-3">
                <CopyRow label={t("skills:trials.bundleUrl")} value={d.bundle_url} hint={t("skills:trials.bundleUrlHint")} />
                {d.manifest_url && <CopyRow label={t("skills:trials.manifestUrl")} value={d.manifest_url} />}
              </div>
            </details>
          )}
          {d.pending_checkpoint ? (
            <CheckpointCard checkpoint={d.pending_checkpoint} step={d.steps.find((s) => s.key === d.pending_checkpoint!.step_key)} actions={actions} snapshot={d.snapshots.filter((x) => x.step_key === d.pending_checkpoint!.step_key && x.iteration === d.pending_checkpoint!.iteration).at(-1) ?? null} />
          ) : tr.state === "testing" || tr.state === "installed" ? (
            <Card><CardBody className="flex items-center gap-3 text-sm text-muted"><Spinner className="h-4 w-4" />{t("skills:trials.waitingAgent")}</CardBody></Card>
          ) : null}
          {(tr.state === "reviewing" || done || tr.state === "testing" || tr.state === "suspended") && <ReviewCard detail={d} actions={actions} done={done} />}
          <HistoryCard checkpoints={d.checkpoints} />
        </div>
        <StepsSidebar steps={d.steps} current={tr.current_step_key} iteration={tr.current_iteration} corrections={tr.corrections} />
      </div>
    </div>
  );
}

function ProposalView({ proposal }: { proposal: Record<string, unknown> }) {
  const entries = Object.entries(proposal).filter(([, v]) => v !== null && v !== undefined && v !== "");
  if (!entries.length) return null;
  return (
    <dl className="space-y-2 text-sm">
      {entries.map(([k, v]) => (
        <div key={k}>
          <dt className="text-xs font-semibold uppercase tracking-wide text-muted">{k.replace(/_/g, " ")}</dt>
          <dd className="whitespace-pre-wrap">{typeof v === "string" ? v : <pre className="overflow-x-auto rounded bg-accent p-2 text-xs">{JSON.stringify(v, null, 2)}</pre>}</dd>
        </div>
      ))}
    </dl>
  );
}

function SnapshotBadge({ snapshot }: { snapshot: TrialSnapshot | null }) {
  const { t } = useTranslation(["skills"]);
  if (!snapshot) return null;
  return (
    <details className="rounded-lg border border-border px-3 py-2 text-xs">
      <summary className="flex cursor-pointer items-center gap-1 font-medium"><Archive className="h-3.5 w-3.5 text-primary" />{t("skills:trials.snapshot.title", { n: snapshot.items.length })}{snapshot.restored_at && <Badge tone="success">{t("skills:trials.snapshot.restored")}</Badge>}</summary>
      <ul className="mt-2 space-y-1 font-mono">
        {snapshot.items.map((it, i) => <li key={i}>{it.kind}: {it.ref}{it.note ? ` (${it.note})` : ""}</li>)}
      </ul>
    </details>
  );
}

function CheckpointCard({ checkpoint, step, actions, snapshot = null }: { checkpoint: Checkpoint; step?: StepDefinition; actions: ReturnType<typeof useTrialActions>; snapshot?: TrialSnapshot | null }) {
  const { t } = useTranslation(["skills", "common"]);
  const [mode, setMode] = useState<"idle" | "change" | "discuss">("idle");
  const [text, setText] = useState("");
  const [discussion, setDiscussion] = useState<Discussion | null>(null);
  const phase = checkpoint.phase;
  const irreversible = step?.side_effects === "irreversible";
  const decide = (decision: string, extra?: { correction_text?: string; updated_instructions?: string }) =>
    actions.decide.mutate({ checkpointId: checkpoint.id, decision, ...extra }, { onError: (e) => toast.error(errorMessage(e, t)), onSuccess: () => { setMode("idle"); setText(""); setDiscussion(null); } });
  const sendDiscussion = (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    actions.discuss.mutate({ checkpointId: checkpoint.id, message: text.trim() }, { onSuccess: (d) => { setDiscussion(d); setText(""); }, onError: (err) => toast.error(errorMessage(err, t)) });
  };
  const latestProposal = discussion?.messages.slice().reverse().find((m) => m.role === "assistant" && m.proposal)?.proposal ?? null;
  return (
    <Card className={cn("border-primary/60", irreversible && phase === "preview" && "border-danger/60")}>
      <CardHeader
        title={<span className="flex items-center gap-2">{t(`skills:trials.phase.${phase}`)} · {step?.title ?? checkpoint.step_key}{irreversible && <AlertTriangle className="h-4 w-4 text-danger" />}</span>}
        description={`${t("skills:trials.iteration", { n: checkpoint.iteration })} · ${t(`skills:trials.execMode.${checkpoint.execution_mode}`, { defaultValue: checkpoint.execution_mode })}`}
      />
      <CardBody className="space-y-4">
        {phase === "restore" && <p className="rounded-lg bg-primary/10 px-3 py-2 text-sm">{t("skills:trials.restoreHelp")}</p>}
        <ProposalView proposal={checkpoint.proposal} />
        <SnapshotBadge snapshot={snapshot} />
        {irreversible && phase === "preview" && <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">{t("skills:trials.irreversibleWarning")}</p>}
        {mode === "idle" && (
          <div className="flex flex-wrap gap-2">
            {phase === "explain" && <Button onClick={() => decide("continue")}><Check className="h-4 w-4" />{t("skills:trials.decisions.continue")}</Button>}
            {phase === "preview" && <Button onClick={() => decide("continue")}><Check className="h-4 w-4" />{t("skills:trials.decisions.continuePreview")}</Button>}
            {phase === "preview" && irreversible && checkpoint.execution_mode === "real" && <Button variant="danger" onClick={() => { if (window.confirm(t("skills:trials.authorizeConfirm"))) decide("authorize_execute"); }}>{t("skills:trials.decisions.authorize_execute")}</Button>}
            {phase === "execute" && <Button onClick={() => decide("continue")}><Check className="h-4 w-4" />{t("skills:trials.decisions.continue")}</Button>}
            {phase === "verify" && <Button onClick={() => decide("approve_and_authorize_next")}><Check className="h-4 w-4" />{t("skills:trials.decisions.approve_and_authorize_next")}</Button>}
            {phase === "restore" && <Button onClick={() => decide("continue")}><Check className="h-4 w-4" />{t("skills:trials.decisions.restoredContinue")}</Button>}
            {(phase === "execute" || phase === "verify") && (checkpoint.execution_mode === "real" || checkpoint.execution_mode === "sandbox_copy") && snapshot && <Button variant="outline" onClick={() => { if (window.confirm(t("skills:trials.restoreConfirm"))) decide("restore"); }}><Undo2 className="h-4 w-4" />{t("skills:trials.decisions.restore")}</Button>}
            {phase !== "restore" && <Button variant="outline" onClick={() => setMode("change")}><RotateCcw className="h-4 w-4" />{t("skills:trials.decisions.change")}</Button>}
            {phase !== "restore" && <Button variant="outline" onClick={() => setMode("discuss")}><MessageSquare className="h-4 w-4" />{t("skills:trials.decisions.discuss")}</Button>}
            {(phase === "preview" || phase === "verify") && <Button variant="ghost" onClick={() => decide("redo")}>{t("skills:trials.decisions.redo")}</Button>}
            {(phase === "explain" || phase === "preview") && <Button variant="ghost" onClick={() => decide("skip")}><SkipForward className="h-4 w-4" />{t("skills:trials.decisions.skip")}</Button>}
            <Button variant="ghost" className="ml-auto text-danger" onClick={() => { if (window.confirm(t("skills:trials.stopConfirm"))) decide("stop"); }}><Square className="h-4 w-4" />{t("skills:trials.decisions.stop")}</Button>
          </div>
        )}
        {mode === "change" && (
          <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); if (text.trim()) decide("change", { correction_text: text.trim(), updated_instructions: text.trim() }); }}>
            <Field label={t("skills:trials.changeLabel")} hint={t("skills:trials.changeHint")}><Textarea autoFocus rows={3} value={text} onChange={(e) => setText(e.target.value)} /></Field>
            <div className="flex gap-2"><Button type="submit" loading={actions.decide.isPending}>{t("skills:trials.sendChange")}</Button><Button variant="outline" onClick={() => setMode("idle")}>{t("common:actions.cancel")}</Button></div>
          </form>
        )}
        {mode === "discuss" && (
          <div className="space-y-3">
            {discussion?.messages.map((m, i) => (
              <div key={i} className={cn("rounded-xl px-3 py-2 text-sm whitespace-pre-wrap", m.role === "user" ? "bg-primary/10" : "bg-accent")}>
                <span className="text-xs font-semibold text-muted">{m.role === "user" ? t("skills:interview.you") : t("skills:trials.coach")}</span>
                <p>{m.content}</p>
                {m.proposal?.new_instruction && <p className="mt-2 rounded border border-border bg-card p-2 text-xs"><span className="font-semibold">{t("skills:trials.proposedInstruction")}:</span> {m.proposal.new_instruction}</p>}
              </div>
            ))}
            <form className="flex items-end gap-2" onSubmit={sendDiscussion}>
              <Textarea rows={2} autoFocus placeholder={t("skills:trials.discussPlaceholder")} value={text} onChange={(e) => setText(e.target.value)} />
              <Button type="submit" loading={actions.discuss.isPending}>{t("skills:interview.send")}</Button>
            </form>
            <div className="flex gap-2">
              {latestProposal?.new_instruction && discussion && <Button loading={actions.applyDiscussion.isPending} onClick={() => actions.applyDiscussion.mutate(discussion.id, { onSuccess: () => { toast.success(t("skills:trials.applied")); setMode("idle"); setDiscussion(null); }, onError: (e) => toast.error(errorMessage(e, t)) })}>{t("skills:trials.applyProposal")}</Button>}
              <Button variant="outline" onClick={() => setMode("idle")}>{t("common:actions.back")}</Button>
            </div>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function ReviewCard({ detail, actions, done }: { detail: { trial: { state: string; summary: string | null; outcome: string | null; corrections: unknown[] } }; actions: ReturnType<typeof useTrialActions>; done: boolean }) {
  const { t } = useTranslation(["skills", "common"]);
  const [note, setNote] = useState("");
  const tr = detail.trial;
  const submit = (outcome: string, keep: boolean) => actions.outcome.mutate({ outcome, keep_installed: keep, note: note || undefined }, { onSuccess: () => toast.success(t("skills:trials.outcomeSaved")), onError: (e) => toast.error(errorMessage(e, t)) });
  return (
    <Card>
      <CardHeader title={t("skills:trials.review")} description={t("skills:trials.reviewHelp")} actions={!done ? <Button variant="outline" loading={actions.summary.isPending} onClick={() => actions.summary.mutate()}>{t("skills:trials.summarize")}</Button> : undefined} />
      <CardBody className="space-y-3">
        {tr.summary ? <Markdown source={tr.summary} /> : <p className="text-sm text-muted">{t("skills:trials.noSummary")}</p>}
        {!done && (
          <>
            <Field label={t("skills:trials.note")}><Textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => submit("accepted", true)}>{t("skills:trials.outcomes.acceptKeep")}</Button>
              <Button variant="outline" onClick={() => submit("accepted", false)}>{t("skills:trials.outcomes.acceptRemove")}</Button>
              <Button variant="outline" onClick={() => submit("changes_requested", true)}>{t("skills:trials.outcomes.changes_requested")}</Button>
              <Button variant="outline" onClick={() => submit("major_rework", false)}>{t("skills:trials.outcomes.major_rework")}</Button>
              <Button variant="ghost" className="text-danger" onClick={() => submit("removed", false)}>{t("skills:trials.outcomes.removed")}</Button>
            </div>
            {actions.outcome.isError && <ErrorState message={errorMessage(actions.outcome.error, t)} />}
          </>
        )}
        {done && tr.outcome && <p className="text-sm">{t("skills:trials.finishedHelp", { outcome: t(`skills:trials.outcomes.${tr.outcome}`) })}</p>}
      </CardBody>
    </Card>
  );
}

function HistoryCard({ checkpoints }: { checkpoints: Checkpoint[] }) {
  const { t, i18n } = useTranslation(["skills"]);
  const decided = checkpoints.filter((c) => c.state !== "pending").slice().reverse();
  if (!decided.length) return null;
  return (
    <Card>
      <CardHeader title={t("skills:trials.history")} />
      <ul className="divide-y divide-border">
        {decided.slice(0, 30).map((c) => (
          <li key={c.id} className="flex items-center gap-2 px-5 py-2 text-sm">
            <Badge>{c.step_key}</Badge><span className="text-muted">{t(`skills:trials.phase.${c.phase}`)} #{c.iteration}</span>
            <Badge tone={c.decision === "stop" ? "danger" : c.decision === "change" || c.decision === "redo" || c.decision === "restore" ? "warning" : "success"}>{c.decision ? t(`skills:trials.decisions.${c.decision}`, { defaultValue: c.decision }) : c.state}</Badge>
            {c.proposal?.auto_confirmed === true && <Badge>{t("skills:trials.autoConfirmed")}</Badge>}
            {c.correction_text && <span className="truncate text-xs text-muted">{c.correction_text}</span>}
            <span className="ml-auto text-xs text-muted">{timeAgo(c.decided_at ?? c.created_at, i18n.language)}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function StepsSidebar({ steps, current, iteration, corrections }: { steps: StepDefinition[]; current: string | null; iteration: number; corrections: { step_key: string; text: string }[] }) {
  const { t } = useTranslation(["skills"]);
  if (!steps.length) return <EmptyState title={t("skills:versions.empty")} />;
  return (
    <Card>
      <CardHeader title={t("skills:trials.steps")} />
      <ol className="divide-y divide-border">
        {steps.map((s) => (
          <li key={s.id} className={cn("px-4 py-2 text-sm", current === s.key && "bg-primary/5")}>
            <div className="flex items-center gap-2">
              <span className={cn("flex h-5 w-5 items-center justify-center rounded-full text-xs", s.test_status === "confirmed" ? "bg-success text-white" : s.test_status === "corrected" ? "bg-warning text-white" : "bg-accent text-muted")}>{s.test_status === "confirmed" ? "✓" : s.ordinal}</span>
              <span className="flex-1 truncate font-medium">{s.title}</span>
              {s.side_effects === "irreversible" && <AlertTriangle className="h-3.5 w-3.5 text-danger" />}
            </div>
            <p className="ml-7 text-xs text-muted">{t(`skills:versions.trialMode.${s.trial_mode}`)}{current === s.key ? ` · ${t("skills:trials.iteration", { n: iteration })}` : ""}{corrections.some((c) => c.step_key === s.key) ? ` · ${t("skills:trials.corrected")}` : ""}</p>
          </li>
        ))}
      </ol>
    </Card>
  );
}
