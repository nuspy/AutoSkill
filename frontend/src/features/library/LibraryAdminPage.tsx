import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Plus, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";
import { useArtifactMutations, useLibrary, useLibraryMutations } from "@/api/hooks/versions";
import type { LibraryComponent } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { Badge, EmptyState, ErrorState } from "@/components/ui/misc";
import { errorMessage } from "@/lib/errors";

type Form = Partial<LibraryComponent> & { toolsText?: string; envText?: string; installText?: string; pathsText?: string; sourceType?: string; sourceUrl?: string; sourcePackage?: string; sourceRef?: string };

const SOURCE_TYPES = ["package_upload", "pip", "npm", "git_url", "url", "manual"] as const;

const blank: Form = { kind: "mcp_server", slug: "", name: "", description: "", version: "1.0.0", is_enabled: true, tags: [], toolsText: "[]", envText: "[]", installText: '{"command": "", "args": [], "hint": ""}', pathsText: "{}", sourceType: "package_upload", sourceUrl: "", sourcePackage: "", sourceRef: "" };

export default function LibraryAdminPage({ canEdit }: { canEdit: boolean }) {
  const { t } = useTranslation(["skills", "common"]);
  const library = useLibrary(canEdit);
  const { create, update, remove } = useLibraryMutations();
  const artifacts = useArtifactMutations();
  const [form, setForm] = useState<Form | null>(null);
  const [jsonError, setJsonError] = useState<string | null>(null);

  const edit = (c: LibraryComponent) => setForm({ ...c, toolsText: JSON.stringify(c.tools, null, 2), envText: JSON.stringify(c.env_requirements, null, 2), installText: JSON.stringify(c.install, null, 2), pathsText: JSON.stringify(c.install_paths ?? {}, null, 2), sourceType: String(c.source?.type ?? "package_upload"), sourceUrl: String(c.source?.url ?? ""), sourcePackage: String(c.source?.package ?? ""), sourceRef: String(c.source?.ref ?? "") });
  const uploadArtifact = (c: LibraryComponent, file: File | undefined) => {
    if (!file) return;
    artifacts.upload.mutate({ id: c.id, file }, { onSuccess: () => toast.success(t("skills:library.artifactUploaded")), onError: (err) => toast.error(err.message) });
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!form) return;
    let tools, env, install, paths;
    try {
      tools = JSON.parse(form.toolsText || "[]");
      env = JSON.parse(form.envText || "[]");
      install = JSON.parse(form.installText || "{}");
      paths = JSON.parse(form.pathsText || "{}");
      setJsonError(null);
    } catch (err) {
      setJsonError(String(err));
      return;
    }
    const source = { ...(form.source ?? {}), type: form.sourceType, url: form.sourceUrl || undefined, package: form.sourcePackage || undefined, ref: form.sourceRef || undefined };
    const body = { kind: form.kind, slug: form.slug, name: form.name, description: form.description, version: form.version, source, tools, env_requirements: env, install, docs: form.docs ?? null, tags: form.tags ?? [], is_enabled: form.is_enabled ?? true, install_paths: paths };
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
                  <p className="mt-1 text-xs text-muted">
                    {t("skills:library.source")}: {String(c.source?.type ?? "-")}
                    {c.artifact ? <> · {t("skills:library.artifact")}: <code>{c.artifact.filename}</code> ({Math.round(c.artifact.size / 1024)} KB, sha256 {c.artifact.sha256.slice(0, 12)}…)</> : <> · {t("skills:library.noArtifact")}</>}
                  </p>
                </div>
                {canEdit && (
                  <div className="flex gap-1">
                    <label className="inline-flex cursor-pointer items-center gap-1 rounded-md px-2 py-1 text-xs hover:bg-accent">
                      <Upload className="h-3.5 w-3.5" />{t("skills:library.uploadArtifact")}
                      <input type="file" accept=".zip,.whl,.tar.gz,.tgz" className="hidden" onChange={(e) => { uploadArtifact(c, e.target.files?.[0]); e.target.value = ""; }} />
                    </label>
                    {c.artifact && <Button size="sm" variant="ghost" onClick={() => artifacts.remove.mutate(c.id)}>{t("skills:library.removeArtifact")}</Button>}
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
              <Field label={t("skills:library.kind")}><Select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value as LibraryComponent["kind"] })}><option value="mcp_server">{t("skills:library.kinds.mcp_server")}</option><option value="skill">{t("skills:library.kinds.skill")}</option><option value="plugin">{t("skills:library.kinds.plugin")}</option></Select></Field>
              <Field label="Slug"><Input required pattern="[a-z0-9]+(-[a-z0-9]+)*" value={form.slug ?? ""} onChange={(e) => setForm({ ...form, slug: e.target.value })} disabled={!!form.id} /></Field>
            </div>
            <Field label={t("skills:library.name")}><Input required value={form.name ?? ""} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label={t("skills:library.description")}><Textarea required rows={2} value={form.description ?? ""} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label={t("skills:library.version")}><Input value={form.version ?? ""} onChange={(e) => setForm({ ...form, version: e.target.value })} /></Field>
              <label className="mt-6 flex items-center gap-2 text-sm"><input type="checkbox" checked={form.is_enabled ?? true} onChange={(e) => setForm({ ...form, is_enabled: e.target.checked })} />{t("skills:providers.enabled")}</label>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label={t("skills:library.sourceType")} hint={t("skills:library.sourceHint")}>
                <Select value={form.sourceType} onChange={(e) => setForm({ ...form, sourceType: e.target.value })}>{SOURCE_TYPES.map((s) => <option key={s} value={s}>{t(`skills:library.sourceTypes.${s}`)}</option>)}</Select>
              </Field>
              {form.sourceType === "pip" || form.sourceType === "npm" ? (
                <Field label={t("skills:library.sourcePackage")}><Input value={form.sourcePackage ?? ""} onChange={(e) => setForm({ ...form, sourcePackage: e.target.value })} /></Field>
              ) : form.sourceType === "git_url" || form.sourceType === "url" ? (
                <Field label={t("skills:library.sourceUrl")}><Input value={form.sourceUrl ?? ""} onChange={(e) => setForm({ ...form, sourceUrl: e.target.value })} /></Field>
              ) : null}
              {form.sourceType === "git_url" && <Field label={t("skills:library.sourceRef")}><Input value={form.sourceRef ?? ""} onChange={(e) => setForm({ ...form, sourceRef: e.target.value })} /></Field>}
            </div>
            <Field label={t("skills:library.installJson")} hint='{"command": "email-mcp", "args": ["--stdio"], "hint": "pipx install email-mcp"}'><Textarea rows={3} className="font-mono text-xs" value={form.installText} onChange={(e) => setForm({ ...form, installText: e.target.value })} /></Field>
            <Field label={t("skills:library.toolsJson")} hint='[{"name": "send_email", "description": "...", "side_effects": "irreversible"}]'><Textarea rows={3} className="font-mono text-xs" value={form.toolsText} onChange={(e) => setForm({ ...form, toolsText: e.target.value })} /></Field>
            {form.kind !== "mcp_server" && <Field label={t("skills:library.pathsJson")} hint='{"hermes": "~/.hermes/skills/<slug>", "openclaw": "~/.openclaw/skills/<slug>"}'><Textarea rows={2} className="font-mono text-xs" value={form.pathsText} onChange={(e) => setForm({ ...form, pathsText: e.target.value })} /></Field>}
            <Field label={t("skills:library.docs")}><Textarea rows={3} value={form.docs ?? ""} onChange={(e) => setForm({ ...form, docs: e.target.value })} /></Field>
            <Field label={t("skills:library.envJson")} hint='[{"name": "SMTP_PASSWORD", "description": "...", "secret": true}]'><Textarea rows={2} className="font-mono text-xs" value={form.envText} onChange={(e) => setForm({ ...form, envText: e.target.value })} /></Field>
            {jsonError && <ErrorState message={jsonError} />}
            {!!err && <ErrorState message={errorMessage(err, t)} />}
          </form>
        )}
      </Dialog>
    </>
  );
}
