import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Star, Trash2 } from "lucide-react";
import { useAdminHub, useCategories } from "@/api/hooks/hub";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { Badge, EmptyState } from "@/components/ui/misc";

export default function HubAdminTab() {
  const { t, i18n } = useTranslation(["skills", "common"]);
  const { published, feature, createCategory, deleteCategory } = useAdminHub();
  const categories = useCategories();
  const [form, setForm] = useState({ slug: "", en: "", it: "" });
  const lang = i18n.language.slice(0, 2);
  const submit = (e: FormEvent) => { e.preventDefault(); createCategory.mutate({ slug: form.slug, name: { en: form.en, it: form.it || form.en } }, { onSuccess: () => setForm({ slug: "", en: "", it: "" }) }); };
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card>
        <CardHeader title={t("skills:hub.adminPublished")} />
        <CardBody>
          {published.data && published.data.length === 0 && <EmptyState title={t("skills:hub.empty")} />}
          <ul className="divide-y divide-border text-sm">
            {published.data?.map((s) => (
              <li key={s.id} className="flex items-center gap-2 py-2">
                <span className="flex-1">{s.title} <code className="text-xs text-muted">v{s.published_version}</code></span>
                <Badge>{t(`skills:hub.visibilities.${s.visibility}`)}</Badge>
                <Button size="sm" variant={s.is_featured ? "secondary" : "outline"} onClick={() => feature.mutate({ skillId: s.id, featured: !s.is_featured })}><Star className="h-3.5 w-3.5" />{s.is_featured ? t("skills:hub.unfeature") : t("skills:hub.feature")}</Button>
              </li>
            ))}
          </ul>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title={t("skills:hub.categories")} />
        <CardBody className="space-y-3">
          <ul className="divide-y divide-border text-sm">
            {categories.data?.map((c) => <li key={c.id} className="flex items-center gap-2 py-1.5"><span className="flex-1">{c.name[lang] ?? c.name.en} <code className="text-xs text-muted">{c.slug}</code></span><span className="text-xs text-muted">{c.count}</span><Button size="icon" variant="ghost" onClick={() => deleteCategory.mutate(c.id)}><Trash2 className="h-4 w-4 text-danger" /></Button></li>)}
          </ul>
          <form className="grid grid-cols-3 items-end gap-2" onSubmit={submit}>
            <Field label="Slug"><Input required pattern="[a-z0-9]+(-[a-z0-9]+)*" value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value })} /></Field>
            <Field label="EN"><Input required value={form.en} onChange={(e) => setForm({ ...form, en: e.target.value })} /></Field>
            <Field label="IT"><Input value={form.it} onChange={(e) => setForm({ ...form, it: e.target.value })} /></Field>
            <Button type="submit" className="col-span-3" loading={createCategory.isPending}>{t("common:actions.add")}</Button>
          </form>
        </CardBody>
      </Card>
    </div>
  );
}
