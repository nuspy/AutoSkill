import { useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import type { UserRole } from "@/api/types";
import {
  useAdminAudit, useAdminJobs, useAdminProjects, useAdminSaveSettings, useAdminSettings, useAdminStats, useAdminUpdateUser, useAdminUsers,
} from "@/api/hooks/admin";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/input";
import { Badge, ErrorState, PageHeader, Skeleton } from "@/components/ui/misc";
import { errorMessage } from "@/lib/errors";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/cn";
import { ProvidersCard } from "@/features/providers/ProvidersCard";
import LibraryAdminPage from "@/features/library/LibraryAdminPage";
import HubAdminTab from "./HubAdminTab";

const TABS = ["users", "projects", "providers", "library", "hub", "settings", "audit", "jobs"] as const;

export default function AdminPage() {
  const { t } = useTranslation(["admin", "common"]);
  const stats = useAdminStats();
  return (
    <>
      <PageHeader title={t("admin:title")} />
      <div className="mb-6 grid gap-4 sm:grid-cols-4">
        {(["users", "projects", "devices", "jobsRunning"] as const).map((k) => (
          <Card key={k}><CardBody><p className="text-xs uppercase tracking-wide text-muted">{t(`admin:stats.${k}`)}</p><p className="mt-1 text-2xl font-semibold">{stats.data ? stats.data[k === "jobsRunning" ? "jobs_running" : k] : "—"}</p></CardBody></Card>
        ))}
      </div>
      <nav className="mb-4 flex gap-1 border-b border-border">
        {TABS.map((tab) => (
          <NavLink key={tab} to={`/admin/${tab}`} className={({ isActive }) => cn("border-b-2 px-3 py-2 text-sm font-medium", isActive ? "border-primary text-primary" : "border-transparent text-muted hover:text-fg")}>{t(`admin:${tab}`)}</NavLink>
        ))}
      </nav>
      <Routes>
        <Route index element={<Navigate to="users" replace />} />
        <Route path="users" element={<UsersTab />} />
        <Route path="projects" element={<ProjectsTab />} />
        <Route path="providers" element={<ProvidersCard canEdit />} />
        <Route path="library" element={<LibraryAdminPage canEdit />} />
        <Route path="hub" element={<HubAdminTab />} />
        <Route path="settings" element={<SettingsTab />} />
        <Route path="audit" element={<AuditTab />} />
        <Route path="jobs" element={<JobsTab />} />
      </Routes>
    </>
  );
}

function UsersTab() {
  const { t } = useTranslation(["admin", "common"]);
  const [q, setQ] = useState("");
  const users = useAdminUsers(q);
  const update = useAdminUpdateUser();
  const onError = (err: unknown) => toast.error(errorMessage(err, t));
  return (
    <Card>
      <CardHeader title={t("admin:users")} actions={<Input placeholder={t("common:actions.search")} value={q} onChange={(e) => setQ(e.target.value)} className="w-56" />} />
      {users.isLoading ? <CardBody><Skeleton className="h-24" /></CardBody> : (
        <ul className="divide-y divide-border">
          {users.data?.items.map((u) => (
            <li key={u.id} className="flex items-center gap-3 px-5 py-3 text-sm">
              <div className="flex-1"><p className="font-medium">{u.display_name}</p><p className="text-xs text-muted">{u.email}</p></div>
              <Select className="w-40" value={u.role} onChange={(e) => update.mutate({ id: u.id, role: e.target.value as UserRole }, { onSuccess: () => toast.success(t("admin:user.updated")), onError })}>
                {(["admin", "reviewer", "member"] as const).map((r) => <option key={r} value={r}>{t(`common:roles.${r}`)}</option>)}
              </Select>
              <Button size="sm" variant={u.is_active ? "outline" : "secondary"} onClick={() => update.mutate({ id: u.id, is_active: !u.is_active }, { onError })}>{u.is_active ? t("admin:user.active") : t("admin:user.disabled")}</Button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function ProjectsTab() {
  const { t } = useTranslation(["admin", "common"]);
  const projects = useAdminProjects();
  return (
    <Card>
      <CardHeader title={t("admin:projects")} />
      <ul className="divide-y divide-border">
        {projects.data?.map((p) => <li key={p.id} className="px-5 py-3 text-sm"><span className="font-medium">{p.name}</span> <span className="text-muted">· {p.slug}</span></li>)}
      </ul>
    </Card>
  );
}

function SettingsTab() {
  const { t } = useTranslation(["admin", "common"]);
  const settings = useAdminSettings();
  const save = useAdminSaveSettings();
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null);
  if (settings.isLoading || !settings.data) return <Skeleton className="h-40" />;
  const values = draft ?? settings.data;
  return (
    <Card>
      <CardHeader title={t("admin:settings")} actions={<Button loading={save.isPending} onClick={() => save.mutate(values, { onSuccess: () => { toast.success(t("common:status.saved")); setDraft(null); } })}>{t("common:actions.save")}</Button>} />
      <CardBody className="space-y-3">
        {Object.entries(values).map(([key, value]) => (
          <label key={key} className="flex items-center justify-between gap-4 text-sm">
            <span>{t(`admin:setting.${key}`, { defaultValue: key })}</span>
            {typeof value === "boolean" ? (
              <input type="checkbox" className="h-4 w-4" checked={value} onChange={(e) => setDraft({ ...values, [key]: e.target.checked })} />
            ) : (
              <Input className="w-40" type="number" value={String(value)} onChange={(e) => setDraft({ ...values, [key]: Number(e.target.value) })} />
            )}
          </label>
        ))}
        {save.isError && <ErrorState message={errorMessage(save.error, t)} />}
      </CardBody>
    </Card>
  );
}

function AuditTab() {
  const { t, i18n } = useTranslation(["admin"]);
  const audit = useAdminAudit();
  return (
    <Card>
      <CardHeader title={t("admin:audit")} />
      <ul className="divide-y divide-border">
        {audit.data?.items.map((a) => (
          <li key={a.id} className="flex items-center gap-3 px-5 py-2 text-sm">
            <Badge>{a.action}</Badge>
            <span className="flex-1 truncate text-muted">{a.subject_type ?? ""} {a.subject_id ?? ""}</span>
            <span className="text-xs text-muted">{formatDate(a.created_at, i18n.language)}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function JobsTab() {
  const { t, i18n } = useTranslation(["admin"]);
  const jobs = useAdminJobs();
  const tone = (s: string) => (s === "succeeded" ? "success" : s === "failed" ? "danger" : s === "running" ? "warning" : "neutral");
  return (
    <Card>
      <CardHeader title={t("admin:jobs")} />
      <ul className="divide-y divide-border">
        {jobs.data?.items.map((j) => (
          <li key={j.id} className="flex items-center gap-3 px-5 py-2 text-sm">
            <Badge tone={tone(j.status)}>{j.status}</Badge>
            <span className="font-mono text-xs">{j.type}</span>
            <span className="flex-1 truncate text-muted">{j.message ?? j.error?.split("\n")[0] ?? ""}</span>
            <span className="text-xs text-muted">{formatDate(j.created_at, i18n.language)}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
