import { useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Laptop, MonitorSmartphone, TerminalSquare } from "lucide-react";
import { useStartInterview } from "@/api/hooks/skills";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { ErrorState, PageHeader } from "@/components/ui/misc";
import { errorMessage } from "@/lib/errors";
import { LOCALE_NAMES, SUPPORTED_LOCALES } from "@/i18n";

export default function NewSkillPage() {
  const { projectId = "" } = useParams();
  const { t, i18n } = useTranslation(["skills", "common"]);
  const navigate = useNavigate();
  const start = useStartInterview(projectId);
  const [form, setForm] = useState({ title: "", description: "", language: i18n.language.slice(0, 2) || "en" });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    start.mutate(form, { onSuccess: (s) => navigate(`/p/${projectId}/skills/${s.skill_id}/interview/${s.id}`) });
  };

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title={t("skills:start.title")} subtitle={t("skills:start.subtitle")} />
      <Card>
        <CardBody>
          <form className="space-y-5" onSubmit={submit}>
            <Field label={t("skills:start.skillTitle")}>
              <Input required maxLength={200} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
            </Field>
            <Field label={t("skills:start.description")}>
              <Textarea required rows={8} placeholder={t("skills:start.placeholder")} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </Field>
            <Field label={t("skills:start.language")}>
              <Select value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })}>
                {SUPPORTED_LOCALES.map((l) => <option key={l} value={l}>{LOCALE_NAMES[l]}</option>)}
              </Select>
            </Field>
            {start.isError && <ErrorState message={errorMessage(start.error, t)} />}
            <Button type="submit" size="lg" loading={start.isPending}>{t("skills:start.submit")}</Button>
          </form>
        </CardBody>
      </Card>
      <WaysToBuild />
    </div>
  );
}

/** The three ways in. AutoSkill leads all of them: what changes is whether an agent on the person's
 *  machine is there to look things up, and which end the session is opened from. */
function WaysToBuild() {
  const { t } = useTranslation(["skills"]);
  const ways = [
    { key: "here", icon: <MonitorSmartphone className="h-5 w-5" aria-hidden /> },
    { key: "attach", icon: <Laptop className="h-5 w-5" aria-hidden /> },
    { key: "fromAgent", icon: <TerminalSquare className="h-5 w-5" aria-hidden /> },
  ];
  return (
    <section className="mt-6">
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">{t("skills:ways.title")}</h2>
      <ul className="space-y-2">
        {ways.map((w) => (
          <li key={w.key} className="flex gap-3 rounded-xl border border-border p-3">
            <span className="mt-0.5 shrink-0 text-muted">{w.icon}</span>
            <div className="text-sm">
              <p className="font-medium">{t(`skills:ways.${w.key}.title`)}</p>
              <p className="text-muted">{t(`skills:ways.${w.key}.body`)}</p>
              {w.key === "fromAgent" && (
                <code className="mt-1 block rounded bg-accent px-2 py-1 text-xs">autoskill skill new "…"</code>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
