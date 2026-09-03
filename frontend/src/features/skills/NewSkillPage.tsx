import { useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
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
    </div>
  );
}
