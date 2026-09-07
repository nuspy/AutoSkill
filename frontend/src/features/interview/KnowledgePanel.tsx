import { useState } from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, CheckCircle2, ChevronRight, Circle } from "lucide-react";
import type { KnowledgeDoc } from "@/api/types";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/misc";
import { cn } from "@/lib/cn";

export function GateRing({ passed, total }: { passed: number; total: number }) {
  const radius = 22;
  const circumference = 2 * Math.PI * radius;
  const ratio = total ? passed / total : 0;
  return (
    <svg width="56" height="56" viewBox="0 0 56 56" className="shrink-0" role="img" aria-label={`${passed}/${total}`}>
      <circle cx="28" cy="28" r={radius} className="stroke-border" strokeWidth="6" fill="none" />
      <circle cx="28" cy="28" r={radius} className={cn("transition-all", ratio === 1 ? "stroke-success" : "stroke-primary")} strokeWidth="6" fill="none" strokeLinecap="round" strokeDasharray={circumference} strokeDashoffset={circumference * (1 - ratio)} transform="rotate(-90 28 28)" />
      <text x="28" y="32" textAnchor="middle" className="fill-fg text-xs font-semibold">{passed}/{total}</text>
    </svg>
  );
}

function Section({ title, children, empty }: { title: string; children?: React.ReactNode; empty?: boolean }) {
  if (empty) return null;
  return (
    <div>
      <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">{title}</h4>
      <div className="text-sm">{children}</div>
    </div>
  );
}

type DocStep = KnowledgeDoc["doc"]["steps"][number];

/** A step of the skill as the interview understood it. Click to see what was captured — and what
 *  is still missing: an empty section is the fastest way to spot a gate that has not passed. */
function StepItem({ step, index, startOpen }: { step: DocStep; index: number; startOpen: boolean }) {
  const { t } = useTranslation(["skills"]);
  const [open, setOpen] = useState(startOpen);
  const tone = step.side_effects === "irreversible" ? "danger" : step.side_effects === "reversible" ? "warning" : step.side_effects === "unknown" ? "neutral" : "success";
  return (
    <li className="rounded-lg border border-border">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex w-full items-start gap-2 p-2 text-left min-h-11">
        <ChevronRight className={cn("mt-0.5 h-4 w-4 shrink-0 text-muted transition-transform", open && "rotate-90")} aria-hidden />
        <span className="flex-1">
          <span className="flex flex-wrap items-center gap-1.5">
            <span className="font-medium">{index + 1}. {step.title}</span>
            <Badge tone="neutral">{t(`skills:knowledge.kind.${step.kind_hint}`)}</Badge>
            <Badge tone={tone}>
              {step.side_effects === "irreversible" && <AlertTriangle className="mr-1 h-3 w-3" />}
              {t(`skills:knowledge.sideEffects.${step.side_effects}`)}
            </Badge>
          </span>
          {step.description && <span className="mt-1 block text-muted">{step.description}</span>}
        </span>
      </button>
      {open && (
        <div className="space-y-2 border-t border-border px-3 py-2 text-xs">
          {step.decision_rules.length > 0 && (
            <div>
              <h5 className="font-semibold uppercase tracking-wide text-muted">{t("skills:knowledge.rules")}</h5>
              <ul className="mt-0.5 list-disc pl-4">{step.decision_rules.map((r, j) => <li key={j}>{r}</li>)}</ul>
            </div>
          )}
          <div>
            <h5 className="font-semibold uppercase tracking-wide text-muted">{t("skills:knowledge.example")}</h5>
            {step.example ? <p className="mt-0.5 italic">{step.example}</p> : <p className="mt-0.5 text-muted">{t("skills:knowledge.missing")}</p>}
          </div>
          {step.uses.length > 0 && (
            <div>
              <h5 className="font-semibold uppercase tracking-wide text-muted">{t("skills:knowledge.usesSources")}</h5>
              <p className="mt-0.5">{step.uses.join(", ")}</p>
            </div>
          )}
          {step.restore_strategy && step.restore_strategy !== "unknown" && (
            <div>
              <h5 className="font-semibold uppercase tracking-wide text-muted">{t("skills:knowledge.restore")}</h5>
              <p className="mt-0.5">{step.restore_strategy}</p>
            </div>
          )}
          <p className="text-muted">{t("skills:knowledge.noRunYet")}</p>
        </div>
      )}
    </li>
  );
}

export function KnowledgePanel({ knowledge, expanded = false }: { knowledge: KnowledgeDoc; expanded?: boolean }) {
  const { t } = useTranslation(["skills"]);
  const doc = knowledge.doc;
  const gates = knowledge.completeness.gates ?? [];
  return (
    <Card>
      <CardHeader
        title={t("skills:knowledge.title")}
        description={t("skills:knowledge.revision", { n: knowledge.revision })}
        actions={<GateRing passed={knowledge.completeness.passed} total={knowledge.completeness.total} />}
      />
      <CardBody className="space-y-4">
        <ul className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
          {gates.map((g) => (
            <li key={g.id} className="flex items-center gap-1.5" title={g.detail}>
              {g.passed ? <CheckCircle2 className="h-3.5 w-3.5 text-success" /> : <Circle className="h-3.5 w-3.5 text-muted" />}
              <span className={g.passed ? "text-fg" : "text-muted"}>{t(`skills:gates.${g.id}`, { defaultValue: g.title })}</span>
            </li>
          ))}
        </ul>
        <Section title={t("skills:knowledge.goal")} empty={!doc.task.goal}><p>{doc.task.goal}</p></Section>
        <Section title={t("skills:knowledge.trigger")} empty={!doc.task.trigger}><p>{doc.task.trigger}</p></Section>
        <Section title={t("skills:knowledge.sources")} empty={!doc.data_sources.length}>
          <ul className="space-y-1">
            {doc.data_sources.map((s) => (
              <li key={s.ref}><span className="font-medium">{s.ref}</span> <Badge>{s.kind}</Badge> {s.access && <span className="text-muted">· {s.access}</span>}{expanded && s.fields_used.length > 0 && <span className="block text-xs text-muted">{s.fields_used.join(", ")}</span>}</li>
            ))}
          </ul>
        </Section>
        <Section title={t("skills:knowledge.steps")} empty={!doc.steps.length}>
          <ol className="space-y-2">
            {doc.steps.map((step, i) => (
              <StepItem key={step.key} step={step} index={i} startOpen={expanded} />
            ))}
          </ol>
        </Section>
        {expanded && (
          <>
            <Section title={t("skills:knowledge.edgeCases")} empty={!doc.edge_cases.length}>
              <ul className="list-disc pl-5">{doc.edge_cases.map((e, i) => <li key={i}>{e.condition} → {e.expected_handling} {e.confirmed && <CheckCircle2 className="inline h-3 w-3 text-success" />}</li>)}</ul>
            </Section>
            <Section title={t("skills:knowledge.criteria")} empty={!doc.acceptance_criteria.length}>
              <ul className="list-disc pl-5">{doc.acceptance_criteria.map((c) => <li key={c.id}>{c.statement}</li>)}</ul>
            </Section>
            <Section title={t("skills:knowledge.integrations")} empty={!doc.integrations.length}>
              <ul className="list-disc pl-5">{doc.integrations.map((i) => <li key={i.system}><span className="font-medium">{i.system}</span> {i.protocol && <Badge>{i.protocol}</Badge>} {i.purpose}{i.credentials_needed.length > 0 && <span className="text-xs text-muted"> · {i.credentials_needed.join(", ")}</span>}</li>)}</ul>
            </Section>
          </>
        )}
        <Section title={t("skills:knowledge.openQuestions")} empty={!doc.open_questions.length}>
          <ul className="list-disc pl-5 text-warning">{doc.open_questions.map((q, i) => <li key={i}>{q}</li>)}</ul>
        </Section>
      </CardBody>
    </Card>
  );
}
