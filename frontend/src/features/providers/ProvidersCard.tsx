import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Plug, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useProviderMutations, useProviders } from "@/api/hooks/skills";
import type { Provider } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import { Badge, EmptyState, ErrorState } from "@/components/ui/misc";
import { errorMessage } from "@/lib/errors";

const ADAPTERS = ["openai_compat", "anthropic", "openai", "google", "openrouter"];
const PURPOSES = ["interviewer", "supervisor", "author", "coach", "analyst"];

type Form = { id?: string; name: string; adapter: string; model: string; base_url: string; api_key: string; purposes: string[]; is_default: boolean; is_enabled: boolean };
const empty: Form = { name: "", adapter: "openai_compat", model: "", base_url: "", api_key: "", purposes: [], is_default: false, is_enabled: true };

export function ProvidersCard({ projectId, canEdit }: { projectId?: string; canEdit: boolean }) {
  const { t } = useTranslation(["skills", "common"]);
  const providers = useProviders(projectId);
  const { create, update, remove, test } = useProviderMutations(projectId);
  const [form, setForm] = useState<Form | null>(null);
  const rows = (providers.data ?? []).filter((p) => (projectId ? p.scope === "project" : p.scope === "system"));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!form) return;
    const body: Record<string, unknown> = { name: form.name, model: form.model, base_url: form.base_url || null, purposes: form.purposes, is_default: form.is_default, is_enabled: form.is_enabled };
    if (form.api_key) body.api_key = form.api_key;
    if (!form.id) body.adapter = form.adapter;
    const done = () => setForm(null);
    if (form.id) update.mutate({ id: form.id, ...body }, { onSuccess: done });
    else create.mutate(body, { onSuccess: done });
  };
  const edit = (p: Provider) => setForm({ id: p.id, name: p.name, adapter: p.adapter, model: p.model, base_url: p.base_url ?? "", api_key: "", purposes: p.purposes, is_default: p.is_default, is_enabled: p.is_enabled });
  const runTest = (id: string) => test.mutate(id, { onSuccess: (r) => (r.ok ? toast.success(t("skills:providers.testOk", { ms: r.latency_ms })) : toast.error(t("skills:providers.testFail", { message: r.message }))) });
  const err = create.error || update.error;
  return (
    <>
      <Card>
        <CardHeader title={projectId ? t("skills:providers.project") : t("skills:providers.system")} description={t("skills:providers.subtitle")} actions={canEdit ? <Button onClick={() => setForm(empty)}><Plus className="h-4 w-4" />{t("skills:providers.add")}</Button> : undefined} />
        <CardBody>
          {providers.data && rows.length === 0 && <EmptyState title={t("skills:providers.empty")} />}
          <ul className="divide-y divide-border">
            {rows.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center gap-3 py-2 text-sm">
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{p.name} <span className="text-muted">· {p.model}</span> {p.is_default && <Badge tone="primary">{t("skills:providers.default")}</Badge>} {!p.is_enabled && <Badge tone="warning">off</Badge>}</p>
                  <p className="truncate text-xs text-muted">{t(`skills:providers.adapters.${p.adapter}`)} {p.base_url && `· ${p.base_url}`} {p.purposes.length > 0 && `· ${p.purposes.map((x) => t(`skills:providers.purposeNames.${x}`)).join(", ")}`}</p>
                </div>
                {p.health?.ok !== undefined && <Badge tone={p.health.ok ? "success" : "danger"}>{p.health.ok ? `${p.health.latency_ms} ms` : "✕"}</Badge>}
                {canEdit && (
                  <>
                    <Button size="sm" variant="outline" loading={test.isPending && test.variables === p.id} onClick={() => runTest(p.id)}><Plug className="h-3.5 w-3.5" />{t("skills:providers.test")}</Button>
                    <Button size="sm" variant="ghost" onClick={() => edit(p)}>{t("common:actions.edit")}</Button>
                    <Button size="icon" variant="ghost" aria-label={t("common:actions.delete")} onClick={() => remove.mutate(p.id)}><Trash2 className="h-4 w-4 text-danger" /></Button>
                  </>
                )}
              </li>
            ))}
          </ul>
        </CardBody>
      </Card>
      <Dialog open={!!form} onClose={() => setForm(null)} title={t("skills:providers.add")} footer={<><Button variant="outline" onClick={() => setForm(null)}>{t("common:actions.cancel")}</Button><Button form="provider-form" type="submit" loading={create.isPending || update.isPending}>{t("common:actions.save")}</Button></>}>
        {form && (
          <form id="provider-form" className="space-y-3" onSubmit={submit}>
            <Field label={t("skills:providers.name")}><Input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label={t("skills:providers.adapter")}><Select disabled={!!form.id} value={form.adapter} onChange={(e) => setForm({ ...form, adapter: e.target.value })}>{ADAPTERS.map((a) => <option key={a} value={a}>{t(`skills:providers.adapters.${a}`)}</option>)}</Select></Field>
              <Field label={t("skills:providers.model")}><Input required value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} placeholder="llama3.1, claude-sonnet-5…" /></Field>
            </div>
            <Field label={t("skills:providers.baseUrl")}><Input value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} placeholder="http://localhost:11434/v1" /></Field>
            <Field label={t("skills:providers.apiKey")} hint={t("skills:providers.apiKeyHint")}><Input type="password" autoComplete="off" value={form.api_key} onChange={(e) => setForm({ ...form, api_key: e.target.value })} /></Field>
            <Field label={t("skills:providers.purposes")}>
              <div className="flex flex-wrap gap-2">
                {PURPOSES.map((p) => (
                  <label key={p} className="flex items-center gap-1 text-sm"><input type="checkbox" checked={form.purposes.includes(p)} onChange={(e) => setForm({ ...form, purposes: e.target.checked ? [...form.purposes, p] : form.purposes.filter((x) => x !== p) })} />{t(`skills:providers.purposeNames.${p}`)}</label>
                ))}
              </div>
            </Field>
            <div className="flex gap-4 text-sm">
              <label className="flex items-center gap-1"><input type="checkbox" checked={form.is_default} onChange={(e) => setForm({ ...form, is_default: e.target.checked })} />{t("skills:providers.default")}</label>
              <label className="flex items-center gap-1"><input type="checkbox" checked={form.is_enabled} onChange={(e) => setForm({ ...form, is_enabled: e.target.checked })} />{t("skills:providers.enabled")}</label>
            </div>
            {!!err && <ErrorState message={errorMessage(err, t)} />}
          </form>
        )}
      </Dialog>
    </>
  );
}
