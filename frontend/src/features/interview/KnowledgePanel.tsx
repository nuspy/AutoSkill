import { useTranslation } from "react-i18next";
import { AlertTriangle, CheckCircle2, Circle } from "lucide-react";
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
              <li key={step.key} className="rounded-lg border border-border p-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="font-medium">{i + 1}. {step.title}</span>
                  <Badge tone="neutral">{t(`skills:knowledge.kind.${step.kind_hint}`)}</Badge>
                  <Badge tone={step.side_effects === "irreversible" ? "danger" : step.side_effects === "reversible" ? "warning" : step.side_effects === "unknown" ? "neutral" : "success"}>
                    {step.side_effects === "irreversible" && <AlertTriangle className="mr-1 h-3 w-3" />}{t(`skills:knowledge.sideEffects.${step.side_effects}`)}
                  </Badge>
                </div>
                {step.description && <p className="mt-1 text-muted">{step.description}</p>}
                {expanded && step.decision_rules.length > 0 && <ul className="mt-1 list-disc pl-5 text-xs">{step.decision_rules.map((r, j) => <li key={j}>{r}</li>)}</ul>}
                {expanded && step.example && <p className="mt-1 text-xs italic text-muted">{step.example}</p>}
              </li>
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
