import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AlertTriangle, Archive, Check, MessageSquare, PauseCircle, Play, PlayCircle, RotateCcw, SkipForward, Square, Undo2 } from "lucide-react";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import { useTrial, useTrialActions } from "@/api/hooks/trials";
import { useLocalAgent } from "@/api/hooks/localAgent";
import { runLocal } from "@/lib/localAgent";
import type { Checkpoint, Discussion, Run, StepDefinition, TrialCreated, TrialSnapshot } from "@/api/types";
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
  // Held only for this visit: the token must not be written anywhere it could be read later.
  const [command, setCommand] = useState<TrialCreated | null>(null);
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
        {tr.outcome && <Badge tone="success">{t(`skills:trials.outcomeDone.${tr.outcome}`)}</Badge>}
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
                <InstallInstructions detail={d} actions={actions} command={command} setCommand={setCommand} />
                <InstallGuide versionId={tr.skill_version_id} trial />
              </CardBody>
            </Card>
          )}
          {/* Once installing is over these instructions stop dominating the page, but they must stay
              whole. They used to shrink to the two public download addresses, dropping the command
              that carries the trial token and the sentence to hand an agent — the two things a person
              actually needs to get the trial moving. What is left of a trial that will not start is
              precisely the part that was cut. It opens by itself while nothing has run yet. */}
          {!done && tr.state !== "requested" && (
            <details className="rounded-lg border border-border p-3 text-sm" open={d.runs.length === 0}>
              <summary className="cursor-pointer font-medium">{t("skills:trials.installInstructions")}</summary>
              <div className="mt-3">
                <InstallInstructions detail={d} actions={actions} command={command} setCommand={setCommand} downloads={false} />
              </div>
            </details>
          )}
          {d.pending_checkpoint ? (
            <CheckpointCard checkpoint={d.pending_checkpoint} step={d.steps.find((s) => s.key === d.pending_checkpoint!.step_key)} actions={actions} snapshot={d.snapshots.filter((x) => x.step_key === d.pending_checkpoint!.step_key && x.iteration === d.pending_checkpoint!.iteration).at(-1) ?? null} />
          ) : tr.state === "testing" || tr.state === "installed" ? (
            <WaitingCard detail={d} />
          ) : null}
          {(tr.state === "reviewing" || done || tr.state === "testing" || tr.state === "suspended") && <ReviewCard detail={d} actions={actions} done={done} />}
          <HistoryCard checkpoints={d.checkpoints} />
        </div>
        <StepsSidebar steps={d.steps} current={tr.current_step_key} iteration={tr.current_iteration} corrections={tr.corrections} trial={tr} skillName={d.skill_name} />
      </div>
    </div>
  );
}

/** Everything needed to install this trial, in the same shape and order as the creation dialog.
 *
 * One component for both places on purpose. They were written twice and drifted: the dialog handed
 * over the command with the token, the address of the installation description and the sentence to
 * paste into an agent, while the trial page kept only the two public addresses. Someone who closed
 * the dialog — which is everyone, since the page is where you go next — could no longer reach the
 * command at all, and the page offered no hint that anything was missing.
 *
 * The command is the first thing because it is the whole of what has to be done. The server keeps a
 * readable copy of the trial's token, so what is shown here is the token already in use — displaying
 * it changes nothing. The re-issue button survives only for trials created before that copy existed,
 * and for those it still costs the previous token, which is why it stays a deliberate press. */
function InstallInstructions({
  detail,
  actions,
  command,
  setCommand,
  downloads = true,
}: {
  detail: { bundle_url: string | null; manifest_url: string | null; cli_command: string | null; session_token: string | null };
  actions: ReturnType<typeof useTrialActions>;
  command: TrialCreated | null;
  setCommand: (c: TrialCreated) => void;
  downloads?: boolean;
}) {
  const { t } = useTranslation(["skills", "common"]);
  // The trial's own command, as issued. A token re-issued during this visit wins only because it is
  // the newer one — nothing here mints anything, and merely opening the page must not invalidate a
  // token an agent may already be using.
  const cliCommand = command?.cli_command ?? detail.cli_command;
  const token = command?.session_token ?? detail.session_token;
  // After the helper installs, the trial has moved on: the page has to ask again rather than keep
  // showing the state it had before the thing it just triggered.
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: ["trials"] });
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">{t("skills:trials.createdHelp")}</p>
      {cliCommand ? (
        <CopyRow
          label={t("skills:trials.cliCommand")}
          value={cliCommand}
          hint={t("skills:trials.tokenWarning")}
          action={
            detail.manifest_url && token
              ? { op: "trial_install", params: { manifest_url: detail.manifest_url, token }, onDone: refresh }
              : undefined
          }
        />
      ) : (
        <div className="space-y-2 rounded-lg border border-primary/40 bg-primary/5 p-3">
          <p className="text-sm">{t("skills:trials.commandLost")}</p>
          <Button
            size="sm"
            loading={actions.reissue.isPending}
            onClick={() => actions.reissue.mutate(undefined, { onSuccess: setCommand, onError: (e) => toast.error(errorMessage(e, t)) })}
          >
            {t("skills:trials.showCommand")}
          </Button>
          <p className="text-xs text-muted">{t("skills:trials.showCommandHint")}</p>
        </div>
      )}
      {detail.bundle_url && (
        <div className="space-y-3 rounded-lg border border-border p-3">
          {/* The two public addresses are shown while the trial is being installed and not afterwards.
              On their own they install nothing: whoever follows them still has to be given the trial
              token, which travels only in the command above. Repeating them once installation is done
              added length without adding a way to act. */}
          {downloads && (
            <>
              <CopyRow label={t("skills:trials.bundleUrl")} value={detail.bundle_url} hint={t("skills:trials.bundleUrlHint")} />
              {detail.manifest_url && <CopyRow label={t("skills:trials.manifestUrl")} value={detail.manifest_url} />}
            </>
          )}
          {/* The sentence carries the token, so it only exists while the token does. It used to be
              rendered unconditionally and told the agent to "ask me for the trial token" — which the
              person could no longer produce, the token having been shown once and never stored. A
              paste-ready instruction that cannot be acted on is worse than no instruction. */}
          {token && (
            <CopyRow
              label={t("skills:trials.tellAgent")}
              value={t("skills:trials.tellAgentText", { url: detail.bundle_url, manifest: detail.manifest_url ?? "", token })}
              hint={t("skills:trials.tokenWarning")}
            />
          )}
        </div>
      )}
    </div>
  );
}

/** Hand a stalled trial back to the local helper to drive on, when the helper is here.
 *
 * The agent started the run and then its own loop stopped between steps. This asks the helper to
 * resume: it does not re-explain the task, it reads where the server says the trial stands and nudges
 * the agent from exactly there through to `end_run`. It is the same `agent_run` the start button
 * calls, told which trial — the driver skips the start when a run is already open. */
function ResumeAgentButton({ target, trialId, prompt, label, size }: { target: string; trialId: string; prompt: string; label?: string; size?: "sm" }) {
  const { t } = useTranslation(["skills", "common"]);
  const { available } = useLocalAgent();
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  if (!available) return null;
  const run = async () => {
    setRunning(true);
    setProgress(null);
    try {
      await runLocal("agent_run", { target, prompt, trial_id: trialId }, setProgress);
      toast.success(t("common:localAgent.done"));
    } catch (err) {
      toast.error(`${(err as Error).message}`);
    } finally {
      setRunning(false);
      setProgress(null);
    }
  };
  return (
    <div className="space-y-1">
      <Button variant="primary" size={size} loading={running} onClick={run}>
        <Play className="h-4 w-4" />
        {label ?? t("skills:trials.resumeAgent")}
      </Button>
      {progress && (
        <p className="flex items-center gap-1 text-xs text-muted">
          <Check className="h-3 w-3 text-success" aria-hidden />
          {progress}
        </p>
      )}
    </div>
  );
}

/** What the page shows while nothing is pending — which is two different situations, not one.
 *
 * It used to show a single spinner and "start the task in your agent" for both. But a trial that the
 * agent never picked up and a trial the agent is actively working through look identical from here,
 * and the first case is the common one: asked to "update the latest Excel list", an agent went
 * looking for a skill by what the task sounded like, never loaded the trial copy, did the work by
 * hand, got half of it wrong and reported success — while this page waited, correctly and for ever,
 * for a step that was never going to arrive.
 *
 * `runs` is what separates them: it is empty until the agent calls `start_run`. So when it is empty
 * the page stops implying the agent is busy and says the one thing that actually unblocks the
 * person — name the skill instead of describing the task. */
function WaitingCard({ detail }: { detail: { runs: Run[]; steps: StepDefinition[]; checkpoints: Checkpoint[]; skill_name: string; trial: { id: string; updated_at: string; target_agent: string } } }) {
  const { t, i18n } = useTranslation(["skills", "common"]);
  const instruction = t("skills:trials.tellAgentSkillText", { skill: detail.skill_name });
  const started = detail.runs.length > 0;
  // A run that has ended is an agent that is not coming back. Waiting on it is waiting on nobody —
  // which is what this page did for a whole trial: the agent hit a refused checkpoint, finished the
  // task without the protocol and called `end_run`, and the page went on promising the next step was
  // about to arrive. The last decided step says how far the walkthrough actually got.
  const last = detail.runs[detail.runs.length - 1];
  if (started && last?.ended_at) {
    const reached = new Set(detail.checkpoints.filter((c) => c.state === "decided").map((c) => c.step_key));
    // What the agent said and what this page witnessed are two different facts, and the card has to
    // keep them apart. Saying the agent "did not finish" when it had finished — and reported a
    // detailed, accurate summary — was simply wrong: what did not finish was the walkthrough. So the
    // agent's own outcome leads, its summary is shown, and the caveat is about verification only.
    const reportedDone = last.status === "succeeded";
    return (
      <Card>
        <CardBody className="space-y-3 text-sm">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            <p className="font-medium">
              {reportedDone ? t("skills:trials.runEndedReported") : t("skills:trials.runEndedTitle")}
            </p>
          </div>
          {last.summary && (
            <blockquote className="border-l-2 border-border pl-3 text-muted">{last.summary}</blockquote>
          )}
          <p className="text-muted">
            {t("skills:trials.runEndedBody", { done: reached.size, total: detail.steps.length })}
          </p>
          <p className="text-xs text-muted">{t("skills:trials.runEndedHint")}</p>
        </CardBody>
      </Card>
    );
  }
  if (started) {
    return (
      <Card>
        <CardBody className="space-y-3 text-sm">
          <p className="flex items-center gap-3 text-muted">
            <Spinner className="h-4 w-4" />
            {t("skills:trials.waitingAgent")}
          </p>
          {/* When the agent's own loop has stopped between steps, this hands the walkthrough back to
              the helper to drive on — it reads where the server says the trial is and nudges the
              agent from there. Shown only when the helper is present; otherwise the person re-prompts
              their agent themselves. */}
          <ResumeAgentButton target={detail.trial.target_agent} trialId={detail.trial.id} prompt={instruction} />
        </CardBody>
      </Card>
    );
  }
  return (
    <Card>
      <CardBody className="space-y-3 text-sm">
        <p className="font-medium">{t("skills:trials.notStartedTitle")}</p>
        <p className="text-muted">{t("skills:trials.notStartedBody")}</p>
        {/* The one command in the whole flow that is not a command: it is a sentence for the agent.
            With a helper that can start the agent, the button hands it over directly — and the
            sentence stays visible, because an agent that cannot be started still has to be told. */}
        <CopyRow
          label={t("skills:trials.tellAgentSkill")}
          value={instruction}
          // With `trial_id`, the helper does not just start the agent — it drives the whole trial,
          // re-nudging it past each decision until `end_run`, so a turn that ends early does not
          // strand the walkthrough. Without the helper the sentence is still there to paste.
          action={{ op: "agent_run", params: { target: detail.trial.target_agent, prompt: instruction, trial_id: detail.trial.id } }}
        />
        <p className="text-xs text-muted">
          {t("skills:trials.notStartedSince", { since: timeAgo(detail.trial.updated_at, i18n.language) })}
        </p>
      </CardBody>
    </Card>
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
          <dd className="whitespace-pre-wrap">{typeof v === "string" ? v : <pre className="overflow-x-auto rounded border border-border bg-card p-2 text-xs">{JSON.stringify(v, null, 2)}</pre>}</dd>
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
    // The step being walked and the list of steps share a tint, so the part of the page that is
    // about steps reads as one region at a glance. `accent` rather than a literal blue: it is the
    // token that already carries a legible light-blue in both themes, where a hard-coded one would
    // turn into a bright panel the moment the page is in dark mode. Inputs keep `bg-card` from their
    // own base class, so every field stays white on top of it without a rule here.
    <Card className={cn("bg-accent border-primary/60", irreversible && phase === "preview" && "border-danger/60")}>
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
              <div key={i} className={cn("rounded-xl px-3 py-2 text-sm whitespace-pre-wrap", m.role === "user" ? "bg-primary/10" : "bg-card")}>
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

function ReviewCard({ detail, actions, done }: { detail: { trial: { id: string; state: string; summary: string | null; outcome: string | null; corrections: unknown[] } }; actions: ReturnType<typeof useTrialActions>; done: boolean }) {
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
        {/* The command carries the trial id. Without it the page named a command that cannot run:
            `autoskill trial accept` on its own exits with "Missing argument 'session'", and the id is
            the one thing the person has no way to guess. */}
        {done && tr.outcome && (
          <div className="space-y-2 text-sm">
            <p>{t("skills:trials.finishedHelp", { outcome: t(`skills:trials.outcomeDone.${tr.outcome}`) })}</p>
            {tr.outcome === "accepted" ? (
              <>
                <CopyRow
                  label={t("skills:trials.keepCommand")}
                  value={`autoskill trial accept ${tr.id}`}
                  hint={t("skills:trials.keepCommandHint")}
                  action={{ op: "trial_settle", params: { session: tr.id, outcome: "accepted", keep: true } }}
                />
                <CopyRow
                  label={t("skills:trials.dropCommand")}
                  value={`autoskill trial accept ${tr.id} --remove`}
                  action={{ op: "trial_settle", params: { session: tr.id, outcome: "accepted", keep: false } }}
                />
              </>
            ) : (
              <CopyRow
                label={t("skills:trials.dropCommand")}
                value={`autoskill trial remove ${tr.id}`}
                action={{ op: "trial_settle", params: { session: tr.id, outcome: "removed" } }}
              />
            )}
          </div>
        )}
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

function StepsSidebar({ steps, current, iteration, corrections, trial, skillName }: { steps: StepDefinition[]; current: string | null; iteration: number; corrections: { step_key: string; text: string }[]; trial: { id: string; target_agent: string }; skillName: string }) {
  const { t } = useTranslation(["skills", "common"]);
  if (!steps.length) return <EmptyState title={t("skills:versions.empty")} />;
  const confirmed = (s: StepDefinition) => s.test_status === "confirmed" || s.test_status === "corrected";
  // The step a re-run would resume at: the first one not yet witnessed. The retry affordance sits on
  // that one step, because the driver picks up there and walks every remaining step in order — a
  // separate button on each unconfirmed step would all do the same thing.
  const firstUnconfirmed = steps.find((s) => !confirmed(s));
  const retryPrompt = t("skills:trials.tellAgentSkillText", { skill: skillName });
  return (
    <Card className="bg-accent">
      <CardHeader title={t("skills:trials.steps")} />
      <ol className="divide-y divide-border">
        {steps.map((s) => (
          <li key={s.id} className={cn("px-4 py-2 text-sm", current === s.key && "bg-primary/15")}>
            <div className="flex items-center gap-2">
              <span className={cn("flex h-5 w-5 items-center justify-center rounded-full text-xs", s.test_status === "confirmed" ? "bg-success text-white" : s.test_status === "corrected" ? "bg-warning text-white" : "bg-card text-muted")}>{s.test_status === "confirmed" ? "✓" : s.ordinal}</span>
              <span className="flex-1 truncate font-medium">{s.title}</span>
              {s.side_effects === "irreversible" && <AlertTriangle className="h-3.5 w-3.5 text-danger" />}
            </div>
            <p className="ml-7 text-xs text-muted">{t(`skills:versions.trialMode.${s.trial_mode}`)}{current === s.key ? ` · ${t("skills:trials.iteration", { n: iteration })}` : ""}{corrections.some((c) => c.step_key === s.key) ? ` · ${t("skills:trials.corrected")}` : ""}{!confirmed(s) && current !== s.key ? ` · ${t("skills:trials.stepUnconfirmed")}` : ""}</p>
            {/* Retry sits on the first unwitnessed step: a step that failed or was skipped no longer
                loses the whole trial, because test status accumulates and a re-run resumes right here. */}
            {firstUnconfirmed?.id === s.id && (
              <div className="ml-7 mt-1.5">
                <ResumeAgentButton target={trial.target_agent} trialId={trial.id} prompt={retryPrompt} label={t("skills:trials.retryStep")} size="sm" />
              </div>
            )}
          </li>
        ))}
      </ol>
    </Card>
  );
}
