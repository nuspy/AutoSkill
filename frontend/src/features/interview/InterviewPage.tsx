import { useEffect, useRef, useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Bot, Send, User as UserIcon } from "lucide-react";
import { useInterview, useInterviewActions } from "@/api/hooks/skills";
import type { InterviewDetail, PendingQuestion } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { Badge, ErrorState, Skeleton, Spinner } from "@/components/ui/misc";
import { errorMessage } from "@/lib/errors";
import { cn } from "@/lib/cn";
import { KnowledgePanel } from "./KnowledgePanel";

const LIVE_STATES = new Set(["created", "intake", "exploring", "gating", "drafting_requested"]);

export default function InterviewPage() {
  const { sessionId = "" } = useParams();
  const { t } = useTranslation(["skills", "common"]);
  const [live, setLive] = useState(true);
  const interview = useInterview(sessionId, live);
  const state = interview.data?.session.state;
  useEffect(() => setLive(!!state && LIVE_STATES.has(state)), [state]);
  const actions = useInterviewActions(sessionId);
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => bottom.current?.scrollIntoView({ behavior: "smooth" }), [interview.data?.messages.length, state]);

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
          {thinking && <div className="flex items-center gap-2 text-sm text-muted"><Spinner className="h-4 w-4" />{t("skills:interview.thinking")}</div>}
          {d.session.state === "failed" && <ErrorState message={`${t("skills:interview.failedTitle")}: ${d.session.error ?? ""}`} />}
          {d.session.state === "complete" && (
            <div className="rounded-xl border border-success/40 bg-success/5 p-4 text-sm">
              <p className="font-medium">{t("skills:interview.completeTitle")}</p>
              <p className="text-muted">{t("skills:interview.completeBody")}</p>
            </div>
          )}
          <div ref={bottom} />
        </CardBody>
        {d.waiting_for === "answer" && d.session.pending_question && <AnswerBox question={d.session.pending_question} onSubmit={(text) => actions.answer.mutate(text)} pending={actions.answer.isPending} error={actions.answer.error} />}
        {d.waiting_for === "confirmation" && <ConfirmBox onConfirm={(confirmed, text) => actions.confirm.mutate({ confirmed, text })} pending={actions.confirm.isPending} error={actions.confirm.error} />}
      </Card>
      <div className="space-y-4">
        {d.knowledge ? <KnowledgePanel knowledge={d.knowledge} /> : <Card><CardBody className="text-sm text-muted">{t("skills:interview.thinking")}</CardBody></Card>}
        {d.session.state !== "complete" && d.session.state !== "abandoned" && (
          <Button variant="ghost" size="sm" className="w-full text-muted" onClick={() => actions.abandon.mutate()}>{t("skills:interview.abandon")}</Button>
        )}
      </div>
    </div>
  );
}

function AnswerBox({ question, onSubmit, pending, error }: { question: PendingQuestion; onSubmit: (text: string) => void; pending: boolean; error: unknown }) {
  const { t } = useTranslation(["skills", "common"]);
  const [text, setText] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    onSubmit(text.trim());
    setText("");
  };
  return (
    <form className="space-y-2 border-t border-border p-4" onSubmit={submit}>
      {question.expects === "choice" && question.options.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {question.options.map((o) => <Button key={o} type="button" size="sm" variant="outline" onClick={() => onSubmit(o)}>{o}</Button>)}
        </div>
      )}
      {question.expects === "yes_no" && (
        <div className="flex gap-2">
          <Button type="button" size="sm" variant="outline" onClick={() => onSubmit(t("skills:interview.yes"))}>{t("skills:interview.yes")}</Button>
          <Button type="button" size="sm" variant="outline" onClick={() => onSubmit(t("skills:interview.no"))}>{t("skills:interview.no")}</Button>
        </div>
      )}
      <div className="flex items-end gap-2">
        <Textarea rows={2} placeholder={t("skills:interview.answer")} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(e as unknown as FormEvent); } }} />
        <Button type="submit" loading={pending} aria-label={t("skills:interview.send")}><Send className="h-4 w-4" /></Button>
      </div>
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
