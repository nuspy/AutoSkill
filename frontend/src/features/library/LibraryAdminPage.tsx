import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useLibrary, useLibraryMutations } from "@/api/hooks/versions";
import type { LibraryComponent } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { Badge, EmptyState, ErrorState } from "@/components/ui/misc";
import { errorMessage } from "@/lib/errors";

type Form = Partial<LibraryComponent> & { toolsText?: string; envText?: string; installText?: string };

const blank: Form = { kind: "mcp_server", slug: "", name: "", description: "", version: "1.0.0", is_enabled: true, tags: [], toolsText: "[]", envText: "[]", installText: '{"command": "", "args": [], "hint": ""}' };

export default function LibraryAdminPage({ canEdit }: { canEdit: boolean }) {
  const { t } = useTranslation(["skills", "common"]);
  const library = useLibrary(canEdit);
  const { create, update, remove } = useLibraryMutations();
  const [form, setForm] = useState<Form | null>(null);
  const [jsonError, setJsonError] = useState<string | null>(null);

  const edit = (c: LibraryComponent) => setForm({ ...c, toolsText: JSON.stringify(c.tools, null, 2), envText: JSON.stringify(c.env_requirements, null, 2), installText: JSON.stringify(c.install, null, 2) });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!form) return;
    let tools, env, install;
    try {
      tools = JSON.parse(form.toolsText || "[]");
      env = JSON.parse(form.envText || "[]");
      install = JSON.parse(form.installText || "{}");
      setJsonError(null);
    } catch (err) {
      setJsonError(String(err));
      return;
    }
    const body = { kind: form.kind, slug: form.slug, name: form.name, description: form.description, version: form.version, source: form.source ?? {}, tools, env_requirements: env, install, docs: form.docs ?? null, tags: form.tags ?? [], is_enabled: form.is_enabled ?? true };
    const done = () => { setForm(null); toast.success(t("common:status.saved")); };
    if (form.id) update.mutate({ id: form.id, ...body }, { onSuccess: done });
    else create.mutate(body, { onSuccess: done });
  };
  const err = create.error || update.error;
  return (
    <>
      <Card>
        <CardHeader title={t("skills:library.title")} description={t("skills:library.subtitle")} actions={canEdit ? <Button onClick={() => setForm(blank)}><Plus className="h-4 w-4" />{t("skills:library.add")}</Button> : undefined} />
        <CardBody>
          {library.data && library.data.length === 0 && <EmptyState title={t("skills:library.empty")} />}
          <ul className="divide-y divide-border">
            {library.data?.map((c) => (
              <li key={c.id} className="flex flex-wrap items-start gap-3 py-3 text-sm">
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{c.name} <code className="text-xs text-muted">{c.slug}</code> <Badge tone="primary">{t(`skills:library.kinds.${c.kind}`)}</Badge> {!c.is_enabled && <Badge tone="warning">off</Badge>} <span className="text-xs text-muted">v{c.version}</span></p>
                  <p className="text-muted">{c.description}</p>
                  {c.tools.length > 0 && <p className="mt-1 text-xs text-muted">{t("skills:library.tools")}: {c.tools.map((x) => x.name).join(", ")}</p>}
                  {c.env_requirements.length > 0 && <p className="text-xs text-muted">{t("skills:library.env")}: {c.env_requirements.map((x) => x.name).join(", ")}</p>}
                </div>
                {canEdit && (
                  <div className="flex gap-1">
                    <Button size="sm" variant="ghost" onClick={() => edit(c)}>{t("common:actions.edit")}</Button>
                    <Button size="icon" variant="ghost" aria-label={t("common:actions.delete")} onClick={() => remove.mutate(c.id)}><Trash2 className="h-4 w-4 text-danger" /></Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </CardBody>
      </Card>
      <Dialog open={!!form} onClose={() => setForm(null)} title={t("skills:library.add")} footer={<><Button variant="outline" onClick={() => setForm(null)}>{t("common:actions.cancel")}</Button><Button form="lib-form" type="submit" loading={create.isPending || update.isPending}>{t("common:actions.save")}</Button></>}>
        {form && (
          <form id="lib-form" className="space-y-3" onSubmit={submit}>
            <div className="grid grid-cols-2 gap-3">
              <Field label={t("skills:library.kind")}><Select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value as "skill" | "mcp_server" })}><option value="mcp_server">{t("skills:library.kinds.mcp_server")}</option><option value="skill">{t("skills:library.kinds.skill")}</option></Select></Field>
              <Field label="Slug"><Input required pattern="[a-z0-9]+(-[a-z0-9]+)*" value={form.slug ?? ""} onChange={(e) => setForm({ ...form, slug: e.target.value })} disabled={!!form.id} /></Field>
            </div>
            <Field label={t("skills:library.name")}><Input required value={form.name ?? ""} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label={t("skills:library.description")}><Textarea required rows={2} value={form.description ?? ""} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label={t("skills:library.version")}><Input value={form.version ?? ""} onChange={(e) => setForm({ ...form, version: e.target.value })} /></Field>
              <label className="mt-6 flex items-center gap-2 text-sm"><input type="checkbox" checked={form.is_enabled ?? true} onChange={(e) => setForm({ ...form, is_enabled: e.target.checked })} />{t("skills:providers.enabled")}</label>
            </div>
            <Field label={t("skills:library.installJson")} hint='{"command": "email-mcp", "args": ["--stdio"], "hint": "pipx install email-mcp"}'><Textarea rows={3} className="font-mono text-xs" value={form.installText} onChange={(e) => setForm({ ...form, installText: e.target.value })} /></Field>
            <Field label={t("skills:library.toolsJson")} hint='[{"name": "send_email", "description": "...", "side_effects": "irreversible"}]'><Textarea rows={3} className="font-mono text-xs" value={form.toolsText} onChange={(e) => setForm({ ...form, toolsText: e.target.value })} /></Field>
            <Field label={t("skills:library.envJson")} hint='[{"name": "SMTP_PASSWORD", "description": "...", "secret": true}]'><Textarea rows={2} className="font-mono text-xs" value={form.envText} onChange={(e) => setForm({ ...form, envText: e.target.value })} /></Field>
            {jsonError && <ErrorState message={jsonError} />}
            {!!err && <ErrorState message={errorMessage(err, t)} />}
          </form>
        )}
      </Dialog>
    </>
  );
}
