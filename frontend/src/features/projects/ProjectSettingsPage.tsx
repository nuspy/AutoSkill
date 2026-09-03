import { useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Copy, Trash2 } from "lucide-react";
import { toast } from "sonner";
import type { ProjectRole } from "@/api/types";
import {
  useAddMember, useCreateApiKey, useDeleteProject, useMembers, useProject, useProjectApiKeys,
  useRemoveMember, useRevokeApiKey, useUpdateMember, useUpdateProject,
} from "@/api/hooks/projects";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { Badge, ErrorState, PageHeader, Skeleton } from "@/components/ui/misc";
import { errorMessage } from "@/lib/errors";
import { formatDate } from "@/lib/format";
import { DataSourcesCard } from "@/features/datasources/DataSourcesCard";
import { ProvidersCard } from "@/features/providers/ProvidersCard";

const ROLES: ProjectRole[] = ["owner", "editor", "viewer"];

export default function ProjectSettingsPage() {
  const { projectId = "" } = useParams();
  const { t, i18n } = useTranslation(["projects", "common"]);
  const navigate = useNavigate();
  const project = useProject(projectId);
  const update = useUpdateProject(projectId);
  const remove = useDeleteProject();
  const members = useMembers(projectId);
  const addMember = useAddMember(projectId);
  const updateMember = useUpdateMember(projectId);
  const removeMember = useRemoveMember(projectId);
  const keys = useProjectApiKeys(projectId);
  const createKey = useCreateApiKey(projectId);
  const revokeKey = useRevokeApiKey(projectId);
  const [form, setForm] = useState<{ name: string; description: string } | null>(null);
  const [member, setMember] = useState<{ email: string; role: ProjectRole }>({ email: "", role: "editor" });
  const [keyName, setKeyName] = useState("");
  const [freshKey, setFreshKey] = useState<string | null>(null);

  if (project.isLoading || !project.data) return <Skeleton className="h-40" />;
  const p = project.data;
  const current = form ?? { name: p.name, description: p.description ?? "" };

  const saveProject = (e: FormEvent) => {
    e.preventDefault();
    update.mutate(current, { onSuccess: () => toast.success(t("common:status.saved")) });
  };
  const submitMember = (e: FormEvent) => {
    e.preventDefault();
    addMember.mutate(member, { onSuccess: () => { toast.success(t("projects:member.added")); setMember({ email: "", role: "editor" }); } });
  };
  const submitKey = (e: FormEvent) => {
    e.preventDefault();
    createKey.mutate({ name: keyName, scopes: ["telemetry:write"] }, { onSuccess: (k) => { setFreshKey(k.key ?? null); setKeyName(""); } });
  };

  return (
    <>
      <PageHeader title={`${p.name} · ${t("projects:settings")}`} />
      <div className="space-y-6">
        <Card>
          <CardHeader title={t("projects:settings")} />
          <CardBody>
            <form className="space-y-4" onSubmit={saveProject}>
              <Field label={t("projects:name")}><Input value={current.name} onChange={(e) => setForm({ ...current, name: e.target.value })} required /></Field>
              <Field label={t("projects:description")}><Textarea value={current.description} onChange={(e) => setForm({ ...current, description: e.target.value })} /></Field>
              {update.isError && <ErrorState message={errorMessage(update.error, t)} />}
              <Button type="submit" loading={update.isPending}>{t("common:actions.save")}</Button>
            </form>
          </CardBody>
        </Card>

        <DataSourcesCard projectId={projectId} />
        <ProvidersCard projectId={projectId} canEdit={p.my_role === "owner"} />

        <Card>
          <CardHeader title={t("projects:members")} />
          <CardBody className="space-y-4">
            <ul className="divide-y divide-border">
              {members.data?.map((m) => (
                <li key={m.id} className="flex items-center gap-3 py-2">
                  <div className="flex-1">
                    <p className="text-sm font-medium">{m.display_name}</p>
                    <p className="text-xs text-muted">{m.email}</p>
                  </div>
                  <Select className="w-36" value={m.role} onChange={(e) => updateMember.mutate({ memberId: m.id, role: e.target.value as ProjectRole }, { onError: (err) => toast.error(errorMessage(err, t)) })}>
                    {ROLES.map((r) => <option key={r} value={r}>{t(`common:roles.${r}`)}</option>)}
                  </Select>
                  <Button variant="ghost" size="icon" aria-label={t("common:actions.remove")} onClick={() => removeMember.mutate(m.id, { onSuccess: () => toast.success(t("projects:member.removed")), onError: (err) => toast.error(errorMessage(err, t)) })}>
                    <Trash2 className="h-4 w-4 text-danger" />
                  </Button>
                </li>
              ))}
            </ul>
            <form className="flex flex-wrap items-end gap-2" onSubmit={submitMember}>
              <div className="min-w-64 flex-1"><Field label={t("projects:member.email")}><Input type="email" required value={member.email} onChange={(e) => setMember({ ...member, email: e.target.value })} /></Field></div>
              <Field label={t("projects:member.role")}>
                <Select value={member.role} onChange={(e) => setMember({ ...member, role: e.target.value as ProjectRole })}>
                  {ROLES.map((r) => <option key={r} value={r}>{t(`common:roles.${r}`)}</option>)}
                </Select>
              </Field>
              <Button type="submit" loading={addMember.isPending}>{t("projects:member.add")}</Button>
            </form>
            {addMember.isError && <ErrorState message={errorMessage(addMember.error, t)} />}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title={t("projects:apiKeys.title")} description={t("projects:apiKeys.subtitle")} />
          <CardBody className="space-y-4">
            {freshKey && (
              <div className="space-y-2 rounded-lg border border-success/40 bg-success/5 p-3 text-sm">
                <p>{t("projects:apiKeys.created")}</p>
                <div className="flex items-center gap-2">
                  <code className="flex-1 overflow-x-auto rounded bg-card px-2 py-1 font-mono text-xs">{freshKey}</code>
                  <Button size="sm" variant="outline" onClick={() => { navigator.clipboard.writeText(freshKey); toast.success(t("common:actions.copied")); }}><Copy className="h-3.5 w-3.5" />{t("common:actions.copy")}</Button>
                </div>
              </div>
            )}
            <ul className="divide-y divide-border">
              {keys.data?.map((k) => (
                <li key={k.id} className="flex items-center gap-3 py-2 text-sm">
                  <div className="flex-1">
                    <p className="font-medium">{k.name} <code className="ml-2 font-mono text-xs text-muted">{k.key_prefix}…</code></p>
                    <p className="text-xs text-muted">{k.scopes.join(", ")} · {t("projects:apiKeys.expires")}: {k.expires_at ? formatDate(k.expires_at, i18n.language) : t("projects:apiKeys.never")}</p>
                  </div>
                  {k.revoked_at ? <Badge tone="danger">{t("projects:apiKeys.revoked")}</Badge> : (
                    <Button size="sm" variant="outline" onClick={() => revokeKey.mutate(k.id, { onSuccess: () => toast.success(t("projects:apiKeys.revoked")) })}>{t("projects:apiKeys.revoke")}</Button>
                  )}
                </li>
              ))}
            </ul>
            <form className="flex items-end gap-2" onSubmit={submitKey}>
              <div className="flex-1"><Field label={t("projects:apiKeys.name")}><Input required value={keyName} onChange={(e) => setKeyName(e.target.value)} /></Field></div>
              <Button type="submit" loading={createKey.isPending}>{t("projects:apiKeys.new")}</Button>
            </form>
          </CardBody>
        </Card>

        <Card className="border-danger/40">
          <CardHeader title={t("projects:danger.title")} />
          <CardBody>
            <Button variant="danger" loading={remove.isPending} onClick={() => { if (window.confirm(t("projects:danger.confirm", { name: p.name }))) remove.mutate(p.id, { onSuccess: () => navigate("/") }); }}>
              <Trash2 className="h-4 w-4" />{t("projects:danger.delete")}
            </Button>
          </CardBody>
        </Card>
      </div>
    </>
  );
}
