import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { useCategories, usePublishSettings } from "@/api/hooks/hub";
import type { Skill } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { errorMessage } from "@/lib/errors";

export function PublishSettingsCard({ skill, canEdit }: { skill: Skill & { category_id?: string | null }; canEdit: boolean }) {
  const { t, i18n } = useTranslation(["skills", "common"]);
  const categories = useCategories();
  const save = usePublishSettings(skill.id);
  const [visibility, setVisibility] = useState(skill.visibility);
  const [category, setCategory] = useState(skill.category_id ?? "");
  const [tags, setTags] = useState(skill.tags.join(", "));
  const lang = i18n.language.slice(0, 2);
  return (
    <Card>
      <CardHeader title={t("skills:hub.settings")} description={t("skills:hub.settingsHelp")} />
      <CardBody className="space-y-3">
        <Field label={t("skills:hub.visibility")} hint={t(`skills:hub.visibilityHelp.${visibility}`)}>
          <Select disabled={!canEdit} value={visibility} onChange={(e) => setVisibility(e.target.value as Skill["visibility"])}>
            {(["private", "shared", "public"] as const).map((v) => <option key={v} value={v}>{t(`skills:hub.visibilities.${v}`)}</option>)}
          </Select>
        </Field>
        <Field label={t("skills:hub.category")}>
          <Select disabled={!canEdit} value={category} onChange={(e) => setCategory(e.target.value)}><option value="">—</option>{categories.data?.map((c) => <option key={c.id} value={c.id}>{c.name[lang] ?? c.name.en ?? c.slug}</option>)}</Select>
        </Field>
        <Field label={t("skills:hub.tags")}><Input disabled={!canEdit} value={tags} onChange={(e) => setTags(e.target.value)} placeholder="invoices, monday" /></Field>
        {canEdit && <Button loading={save.isPending} onClick={() => save.mutate({ visibility, category_id: category || null, tags: tags.split(",").map((x) => x.trim()).filter(Boolean) }, { onSuccess: () => toast.success(t("common:status.saved")), onError: (e) => toast.error(errorMessage(e, t)) })}>{t("common:actions.save")}</Button>}
      </CardBody>
    </Card>
  );
}
