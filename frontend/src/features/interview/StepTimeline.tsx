import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, ChevronRight, RotateCcw, X } from "lucide-react";
import type { InterviewStep } from "@/api/types";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/misc";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

const TONE: Record<InterviewStep["status"], "neutral" | "primary" | "success" | "warning" | "danger"> = {
  running: "primary",
  succeeded: "success",
  failed: "danger",
  waiting: "primary",
  superseded: "neutral",
  discarded: "neutral",
};

/** Steps set aside by a replay are dimmed: still readable, clearly not part of the current run. */
function isPast(status: InterviewStep["status"]) {
  return status === "superseded" || status === "discarded";
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mt-2">
      <h5 className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</h5>
      <div className="mt-0.5 text-sm break-words">{children}</div>
    </div>
  );
}

function StepRow({
  step,
  canReplay,
  onReplay,
  replaying,
}: {
  step: InterviewStep;
  canReplay: boolean;
  onReplay: () => void;
  replaying: boolean;
}) {
  const { t } = useTranslation(["skills"]);
  const [open, setOpen] = useState(false);
  const usage = step.llm_usage;
  const tokens = (usage?.input_tokens ?? 0) + (usage?.output_tokens ?? 0);
  const question = (step.output as { question?: { question?: string } })?.question?.question;
  return (
    <li className={cn("border-b border-border last:border-0", isPast(step.status) && "opacity-60")}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 py-3 text-left min-h-11"
      >
        <ChevronRight className={cn("h-4 w-4 shrink-0 text-muted transition-transform", open && "rotate-90")} aria-hidden />
        <span className="w-6 shrink-0 text-xs tabular-nums text-muted">{step.ordinal}</span>
        <span className="flex-1 truncate text-sm font-medium">{t(`skills:steps.key.${step.key}`, step.key)}</span>
        <Badge tone={TONE[step.status]}>{t(`skills:steps.status.${step.status}`, step.status)}</Badge>
      </button>
      {open && (
        <div className="pb-3 pl-12 pr-2">
          {step.attempt > 1 && <Detail label={t("skills:steps.attempt")}>{step.attempt}</Detail>}
          {question && <Detail label={t("skills:steps.question")}>{question}</Detail>}
          {step.supervisor_decision && (
            <Detail label={t("skills:steps.decision")}>
              {step.supervisor_decision.effective}
              {step.supervisor_decision.failing_gate ? ` — ${step.supervisor_decision.failing_gate}` : ""}
              {step.supervisor_decision.reasons?.length ? (
                <ul className="mt-1 list-disc pl-4 text-muted">
                  {step.supervisor_decision.reasons.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              ) : null}
            </Detail>
          )}
          {step.error && (
            <Detail label={t("skills:steps.error")}>
              <pre className="overflow-x-auto whitespace-pre-wrap text-xs text-danger">{step.error.slice(0, 600)}</pre>
            </Detail>
          )}
          {tokens > 0 && <Detail label={t("skills:steps.tokens")}>{tokens}</Detail>}
          {canReplay && (
            <Button variant="ghost" size="sm" className="mt-3" onClick={onReplay} loading={replaying}>
              <RotateCcw className="h-4 w-4" aria-hidden />
              {t("skills:steps.replay")}
            </Button>
          )}
        </div>
      )}
    </li>
  );
}

export function StepTimeline({
  steps,
  replayFrom,
  onReplay,
  onAccept,
  onDiscard,
  busy,
}: {
  steps: InterviewStep[];
  replayFrom: number | null;
  onReplay: (ordinal: number) => void;
  onAccept: () => void;
  onDiscard: () => void;
  busy: boolean;
}) {
  const { t } = useTranslation(["skills"]);
  const replaying = replayFrom !== null;
  return (
    <Card>
      <CardHeader title={t("skills:steps.title")} description={t("skills:steps.description")} />
      <CardBody className="pt-0">
        {replaying && (
          <div className="mb-3 rounded-xl border border-primary/40 bg-primary/5 p-3">
            <p className="text-sm font-medium">{t("skills:steps.replayActive", { n: replayFrom })}</p>
            <p className="mt-0.5 text-xs text-muted">{t("skills:steps.replayHint")}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button size="sm" onClick={onAccept} disabled={busy}>
                <Check className="h-4 w-4" aria-hidden />
                {t("skills:steps.accept")}
              </Button>
              <Button size="sm" variant="ghost" onClick={onDiscard} disabled={busy}>
                <X className="h-4 w-4" aria-hidden />
                {t("skills:steps.discard")}
              </Button>
            </div>
          </div>
        )}
        {steps.length === 0 ? (
          <p className="py-3 text-sm text-muted">{t("skills:steps.empty")}</p>
        ) : (
          <ul>
            {steps.map((step) => (
              <StepRow
                key={step.id}
                step={step}
                // one replay at a time: while it is open the choice is accept or discard
                canReplay={step.replayable && !replaying}
                onReplay={() => onReplay(step.ordinal)}
                replaying={busy}
              />
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}
