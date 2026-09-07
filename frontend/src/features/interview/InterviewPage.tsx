import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Bot, History, Paperclip, Plus, Send, User as UserIcon, X } from "lucide-react";
import { interviewPollMs, useInterview, useInterviewActions, useInterviewSteps, useUploadAttachment } from "@/api/hooks/skills";
import type { Attachment, InterviewDetail, PendingQuestion } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { Badge, ErrorState, Skeleton, Spinner } from "@/components/ui/misc";
import { alertChime } from "@/lib/chime";
import { errorMessage } from "@/lib/errors";
import { cn } from "@/lib/cn";
import { KnowledgePanel } from "./KnowledgePanel";
import { StepTimeline } from "./StepTimeline";
import { AgentPanel } from "./AgentPanel";

// States that put a bare "thinking" spinner in the transcript. `drafting_requested` is deliberately
// not one of them: the interview is over by then, and the completion panel below says the more useful
// thing — the understanding is done, and the first draft is being written.
const LIVE_STATES = new Set(["created", "intake", "exploring", "gating"]);
// The states in which nothing more happens until the person does something.
const NEEDS_THE_PERSON = new Set(["awaiting_answer", "awaiting_confirmation"]);

export default function InterviewPage() {
  const { sessionId = "" } = useParams();
  const { t } = useTranslation(["skills", "common"]);
  const interview = useInterview(sessionId);
  const state = interview.data?.session.state;
  const actions = useInterviewActions(sessionId);
  const [showSteps, setShowSteps] = useState(false);
  const steps = useInterviewSteps(sessionId, showSteps || !!interview.data?.replay, interviewPollMs(state));
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => bottom.current?.scrollIntoView({ behavior: "smooth" }), [interview.data?.messages.length, state]);

  // Ring when the application starts waiting on the person. It is the *transition* that is worth a
  // sound: opening a page that already has a question on it stays silent, because nothing just
  // happened. This is the moment the sound exists for — a model has thought for four minutes and the
  // person is in another window.
  const previousState = useRef<string | undefined>(undefined);
  useEffect(() => {
    const before = previousState.current;
    previousState.current = state;
    if (before && before !== state && state && NEEDS_THE_PERSON.has(state)) alertChime();
  }, [state]);

  // Last line of defence, and the reason it exists: a single failed request — a proxy handing over a
  // socket the server had just closed — can leave React Query's own scheduler unwilling to try again,
  // and then the page waits for ever on something that already happened. This timer does not consult
  // the query's state at all. While the session is unfinished it simply asks again, and asks
  // immediately whenever the tab comes back into view or the machine comes back online.
  const refetch = interview.refetch;
  const stillRunning = interviewPollMs(state) !== false;
  useEffect(() => {
    if (!sessionId || !stillRunning) return;
    const again = () => void refetch();
    const timer = window.setInterval(again, 15_000);
    document.addEventListener("visibilitychange", again);
    window.addEventListener("online", again);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", again);
      window.removeEventListener("online", again);
    };
  }, [sessionId, stillRunning, refetch]);

  if (interview.isError && !interview.data) return <ErrorState message={errorMessage(interview.error, t)} />;
  if (interview.isLoading || !interview.data) return <Skeleton className="h-96" />;
  const d = interview.data;
  const thinking = LIVE_STATES.has(d.session.state);
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
      <Card className="flex min-h-[60vh] flex-col">
        <div className="flex items-center justify-between border-b border-border px-4 py-2 text-xs text-muted">
          <span className="flex items-center gap-2">
            <Badge tone={d.session.state === "complete" ? "success" : d.session.state === "failed" ? "danger" : "primary"}>{t(`skills:state.${d.session.state}`)}</Badge>
            {t("skills:interview.turns", { count: d.session.turn_count })}
          </span>
          {d.supervisor && (
            <span title={[...d.supervisor.reasons, ...d.supervisor.missing].join("; ")}>
              {t("skills:interview.supervisor")}: {d.supervisor.effective}{d.supervisor.failing_gate && ` · ${t("skills:interview.gate", { id: d.supervisor.failing_gate })}`}
            </span>
          )}
        </div>
        <CardBody className="flex-1 space-y-4 overflow-y-auto">
          {d.messages.map((m) => (
            <div key={m.id} className={cn("flex gap-3", m.role === "user" && "flex-row-reverse")}>
              <div className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-full", m.role === "user" ? "bg-accent" : "bg-primary text-primary-fg")}>
                {m.role === "user" ? <UserIcon className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
              </div>
              <div className={cn("max-w-[80%] rounded-2xl px-4 py-2 text-sm whitespace-pre-wrap", m.role === "user" ? "bg-primary/10" : "bg-accent")}>
                {m.content}
                {typeof m.meta.question === "object" && m.meta.question !== null && (m.meta.question as PendingQuestion).why && (
                  <p className="mt-2 border-t border-border/60 pt-2 text-xs text-muted">{t("skills:interview.why")}: {(m.meta.question as PendingQuestion).why}</p>
                )}
              </div>
            </div>
          ))}
          {/* A failed poll must never look like a slow model. React Query keeps the last good answer
              when a refetch fails, so without this the page goes on showing a spinner over a
              snapshot that may be hours old — which reads as "still working" when in truth nobody is
              listening any more. */}
          {interview.isError ? (
            <div className="space-y-2 rounded-lg border border-danger/40 bg-danger/5 p-3">
              <p className="text-sm font-medium text-danger">{t("skills:interview.disconnected")}</p>
              <p className="text-xs text-muted">{errorMessage(interview.error, t)}</p>
              <Button size="sm" variant="ghost" onClick={() => interview.refetch()} disabled={interview.isFetching}>
                {interview.isFetching ? <Spinner className="h-4 w-4" /> : null}
                {t("skills:interview.reconnect")}
              </Button>
            </div>
          ) : thinking ? (
            // The spinner says what the server was doing at `dataUpdatedAt`, which is not necessarily
            // now — so it says when. A page that has quietly stopped asking then shows a time that
            // stops advancing, instead of looking exactly like a model taking its time.
            <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
              <Spinner className="h-4 w-4" />
              <span>{t("skills:interview.thinking")}</span>
              <Button variant="ghost" size="sm" onClick={() => interview.refetch()} disabled={interview.isFetching}>
                {t("skills:interview.lastChecked", { time: new Date(interview.dataUpdatedAt).toLocaleTimeString() })}
              </Button>
            </div>
          ) : null}
          {d.session.state === "failed" && (
            <div className="space-y-2">
              <ErrorState message={`${t("skills:interview.failedTitle")}: ${d.session.error ?? ""}`} />
              <Button size="sm" onClick={() => actions.retry.mutate()} disabled={actions.retry.isPending}>
                {actions.retry.isPending ? <Spinner className="h-4 w-4" /> : null}
                {t("skills:interview.retry")}
              </Button>
              <p className="text-xs text-muted">{t("skills:interview.retryHint")}</p>
              {!!actions.retry.error && <ErrorState message={errorMessage(actions.retry.error, t)} />}
            </div>
          )}
          {/* The end of an interview used to be four lines of prose and nowhere to click, which left
              the person exactly where the work was finished and the result was two tabs away. */}
          {(d.session.state === "complete" || d.session.state === "drafting_requested") && (
            <div className="rounded-xl border border-success/40 bg-success/5 p-4 text-sm">
              <p className="font-medium">{t("skills:interview.completeTitle")}</p>
              <p className="text-muted">{t("skills:interview.completeBody")}</p>
              {d.session.state === "drafting_requested" ? (
                <p className="mt-3 flex items-center gap-2 text-muted">
                  <Spinner className="h-4 w-4" />
                  {t("skills:interview.drafting")}
                </p>
              ) : (
                <Link
                  to={`/p/${d.session.project_id}/skills/${d.session.skill_id}/versions`}
                  className="mt-3 inline-flex h-11 items-center rounded-lg bg-primary px-4 font-medium text-primary-fg"
                >
                  {t("skills:interview.openDraft")}
                </Link>
              )}
            </div>
          )}
          <div ref={bottom} />
        </CardBody>
        {d.waiting_for === "answer" && d.session.pending_question && <AnswerBox question={d.session.pending_question} projectId={d.session.project_id} onSubmit={(text, attachments) => actions.answer.mutate({ text, attachments })} pending={actions.answer.isPending} error={actions.answer.error} />}
        {d.waiting_for === "confirmation" && <ConfirmBox onConfirm={(confirmed, text) => actions.confirm.mutate({ confirmed, text })} pending={actions.confirm.isPending} error={actions.confirm.error} />}
      </Card>
      <div className="space-y-4">
        {d.knowledge ? <KnowledgePanel knowledge={d.knowledge} /> : <Card><CardBody className="text-sm text-muted">{t("skills:interview.thinking")}</CardBody></Card>}
        {d.session.state !== "complete" && d.session.state !== "abandoned" && (
          <AgentPanel sessionId={sessionId} detail={d} />
        )}
        {(showSteps || d.replay) && (
          <StepTimeline
            steps={steps.data ?? []}
            replayFrom={d.replay?.from_ordinal ?? null}
            onReplay={(ordinal) => actions.replay.mutate(ordinal)}
            onAccept={() => actions.acceptReplay.mutate()}
            onDiscard={() => actions.discardReplay.mutate()}
            busy={actions.replay.isPending || actions.acceptReplay.isPending || actions.discardReplay.isPending}
          />
        )}
        {!d.replay && (
          <Button variant="ghost" size="sm" className="w-full text-muted" onClick={() => setShowSteps((v) => !v)}>
            <History className="h-4 w-4" aria-hidden />
            {t(showSteps ? "skills:steps.hide" : "skills:steps.show")}
          </Button>
        )}
        {d.session.state !== "complete" && d.session.state !== "abandoned" && !d.replay && (
          <Button variant="ghost" size="sm" className="w-full text-muted" onClick={() => actions.abandon.mutate()}>{t("skills:interview.abandon")}</Button>
        )}
      </div>
    </div>
  );
}

function AnswerBox({ question, projectId, onSubmit, pending, error }: { question: PendingQuestion; projectId: string; onSubmit: (text: string, attachments: Attachment[]) => void; pending: boolean; error: unknown }) {
  const { t } = useTranslation(["skills", "common"]);
  const [text, setText] = useState("");
  const [files, setFiles] = useState<Attachment[]>([]);
  const picker = useRef<HTMLInputElement>(null);
  const upload = useUploadAttachment(projectId);
  const pick = (list: FileList | null) => {
    for (const file of Array.from(list ?? [])) {
      upload.mutate(file, { onSuccess: (a) => setFiles((prev) => [...prev, a]) });
    }
    if (picker.current) picker.current.value = "";
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    // a file on its own is an answer: the model reads its preview
    if (!text.trim() && files.length === 0) return;
    onSubmit(text.trim(), files);
    setText("");
    setFiles([]);
  };
  return (
    <form className="space-y-2 border-t border-border p-4" onSubmit={submit}>
      {question.expects === "choice" && question.options.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {question.options.map((o) => <Button key={o} type="button" size="sm" variant="outline" onClick={() => onSubmit(o, [])}>{o}</Button>)}
        </div>
      )}
      {question.expects === "yes_no" && (
        <div className="flex gap-2">
          <Button type="button" size="sm" variant="outline" onClick={() => onSubmit(t("skills:interview.yes"), [])}>{t("skills:interview.yes")}</Button>
          <Button type="button" size="sm" variant="outline" onClick={() => onSubmit(t("skills:interview.no"), [])}>{t("skills:interview.no")}</Button>
        </div>
      )}
      {files.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {files.map((f) => (
            <li key={f.hash + f.name} className="flex items-center gap-1.5 rounded-lg border border-border px-2 py-1 text-xs">
              <Paperclip className="h-3 w-3 text-muted" aria-hidden />
              <span className="max-w-40 truncate">{f.name}</span>
              <button type="button" onClick={() => setFiles((prev) => prev.filter((x) => x !== f))} aria-label={t("common:actions.remove")} className="text-muted hover:text-danger">
                <X className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex items-end gap-2">
        <input ref={picker} type="file" multiple className="hidden" onChange={(e) => pick(e.target.files)} />
        <Button type="button" variant="ghost" size="icon" onClick={() => picker.current?.click()} loading={upload.isPending} aria-label={t("skills:interview.attach")} title={t("skills:interview.attach")}>
          <Plus className="h-4 w-4" />
        </Button>
        <Textarea rows={2} placeholder={t("skills:interview.answer")} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(e as unknown as FormEvent); } }} />
        <Button type="submit" loading={pending} aria-label={t("skills:interview.send")}><Send className="h-4 w-4" /></Button>
      </div>
      {!!upload.error && <ErrorState message={errorMessage(upload.error, t)} />}
      {!!error && <ErrorState message={errorMessage(error, t)} />}
    </form>
  );
}

function ConfirmBox({ onConfirm, pending, error }: { onConfirm: (confirmed: boolean, text?: string) => void; pending: boolean; error: unknown }) {
  const { t } = useTranslation(["skills", "common"]);
  const [correcting, setCorrecting] = useState(false);
  const [text, setText] = useState("");
  return (
    <div className="space-y-2 border-t border-border p-4">
      {!correcting ? (
        <div className="flex gap-2">
          <Button loading={pending} onClick={() => onConfirm(true)}>{t("skills:interview.confirm")}</Button>
          <Button variant="outline" onClick={() => setCorrecting(true)}>{t("skills:interview.correct")}</Button>
        </div>
      ) : (
        <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim()) onConfirm(false, text.trim()); }}>
          <Textarea rows={2} autoFocus placeholder={t("skills:interview.correctionPlaceholder")} value={text} onChange={(e) => setText(e.target.value)} />
          <Button type="submit" loading={pending}>{t("skills:interview.sendCorrection")}</Button>
        </form>
      )}
      {!!error && <ErrorState message={errorMessage(error, t)} />}
    </div>
  );
}

export type { InterviewDetail };
