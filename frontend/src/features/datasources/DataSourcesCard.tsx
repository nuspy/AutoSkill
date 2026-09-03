import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Plus, Trash2 } from "lucide-react";
import { useDataSourceMutations, useDataSources } from "@/api/hooks/skills";
import type { DataSource } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { Badge, EmptyState, ErrorState } from "@/components/ui/misc";
import { errorMessage } from "@/lib/errors";

const KINDS = ["file", "spreadsheet", "email", "web_app", "database", "api", "folder", "other"];
const SENS = ["none", "internal", "pii", "secret"];

export function DataSourcesCard({ projectId }: { projectId: string }) {
  const { t } = useTranslation(["skills", "common"]);
  const sources = useDataSources(projectId);
  const { create, update, remove } = useDataSourceMutations(projectId);
  const [editing, setEditing] = useState<Partial<DataSource> | null>(null);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!editing) return;
    const body = { name: editing.name, kind: editing.kind, description: editing.description, access_notes: editing.access_notes, sensitivity: editing.sensitivity };
    const done = () => setEditing(null);
    if (editing.id) update.mutate({ id: editing.id, ...body }, { onSuccess: done });
    else create.mutate(body, { onSuccess: done });
  };
  const err = create.error || update.error;
  return (
    <>
      <Card>
        <CardHeader title={t("skills:dataSources.title")} description={t("skills:dataSources.subtitle")} actions={<Button onClick={() => setEditing({ kind: "spreadsheet", sensitivity: "internal" })}><Plus className="h-4 w-4" />{t("skills:dataSources.add")}</Button>} />
        <CardBody>
          {sources.data && sources.data.length === 0 && <EmptyState title={t("skills:dataSources.empty")} />}
          <ul className="divide-y divide-border">
            {sources.data?.map((s) => (
              <li key={s.id} className="flex items-center gap-3 py-2 text-sm">
                <div className="flex-1">
                  <p className="font-medium">{s.name} <Badge>{t(`skills:dataSources.kinds.${s.kind}`)}</Badge> <Badge tone={s.sensitivity === "pii" || s.sensitivity === "secret" ? "warning" : "neutral"}>{t(`skills:dataSources.sensitivities.${s.sensitivity}`)}</Badge></p>
                  <p className="text-xs text-muted">{s.access_notes || s.description || ""}</p>
                </div>
                <Button size="sm" variant="ghost" onClick={() => setEditing(s)}>{t("common:actions.edit")}</Button>
                <Button size="icon" variant="ghost" aria-label={t("common:actions.delete")} onClick={() => remove.mutate(s.id)}><Trash2 className="h-4 w-4 text-danger" /></Button>
              </li>
            ))}
          </ul>
        </CardBody>
      </Card>
      <Dialog open={!!editing} onClose={() => setEditing(null)} title={t("skills:dataSources.add")} footer={<><Button variant="outline" onClick={() => setEditing(null)}>{t("common:actions.cancel")}</Button><Button form="ds-form" type="submit" loading={create.isPending || update.isPending}>{t("common:actions.save")}</Button></>}>
        {editing && (
          <form id="ds-form" className="space-y-3" onSubmit={submit}>
            <Field label={t("skills:dataSources.name")}><Input required value={editing.name ?? ""} onChange={(e) => setEditing({ ...editing, name: e.target.value })} /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label={t("skills:dataSources.kind")}><Select value={editing.kind} onChange={(e) => setEditing({ ...editing, kind: e.target.value })}>{KINDS.map((k) => <option key={k} value={k}>{t(`skills:dataSources.kinds.${k}`)}</option>)}</Select></Field>
              <Field label={t("skills:dataSources.sensitivity")}><Select value={editing.sensitivity} onChange={(e) => setEditing({ ...editing, sensitivity: e.target.value })}>{SENS.map((k) => <option key={k} value={k}>{t(`skills:dataSources.sensitivities.${k}`)}</option>)}</Select></Field>
            </div>
            <Field label={t("skills:dataSources.description")}><Textarea rows={2} value={editing.description ?? ""} onChange={(e) => setEditing({ ...editing, description: e.target.value })} /></Field>
            <Field label={t("skills:dataSources.access")}><Textarea rows={2} value={editing.access_notes ?? ""} onChange={(e) => setEditing({ ...editing, access_notes: e.target.value })} /></Field>
            {!!err && <ErrorState message={errorMessage(err, t)} />}
          </form>
        )}
      </Dialog>
    </>
  );
}
