import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Plus, Users } from "lucide-react";
import { toast } from "sonner";
import { useCreateProject, useProjects } from "@/api/hooks/projects";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/input";
import { Badge, EmptyState, ErrorState, PageHeader, Skeleton } from "@/components/ui/misc";
import { errorMessage } from "@/lib/errors";
import { timeAgo } from "@/lib/format";

export default function ProjectsPage() {
  const { t, i18n } = useTranslation(["projects", "common"]);
  const projects = useProjects();
  const create = useCreateProject();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", description: "" });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate(form, {
      onSuccess: () => {
        toast.success(t("projects:created"));
        setOpen(false);
        setForm({ name: "", description: "" });
      },
    });
  };

  return (
    <>
      <PageHeader title={t("projects:title")} subtitle={t("projects:subtitle")} actions={<Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" />{t("projects:new")}</Button>} />
      {projects.isLoading && <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-32" />)}</div>}
      {projects.isError && <ErrorState message={errorMessage(projects.error, t)} onRetry={() => projects.refetch()} retryLabel={t("common:actions.retry")} />}
      {projects.data && projects.data.length === 0 && (
        <EmptyState title={t("common:status.empty")} description={t("projects:empty")} action={<Button onClick={() => setOpen(true)}>{t("projects:new")}</Button>} />
      )}
      {projects.data && projects.data.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects.data.map((p) => (
            <Link key={p.id} to={`/p/${p.id}`} className="group">
              <Card className="h-full transition group-hover:border-primary/50 group-hover:shadow-md">
                <CardBody className="flex h-full flex-col">
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="font-semibold">{p.name}</h3>
                    {p.my_role && <Badge tone="primary">{t(`common:roles.${p.my_role}`)}</Badge>}
                  </div>
                  <p className="mt-1 line-clamp-2 flex-1 text-sm text-muted">{p.description || "—"}</p>
                  <div className="mt-3 flex items-center justify-between text-xs text-muted">
                    <span className="flex items-center gap-1"><Users className="h-3.5 w-3.5" />{p.member_count}</span>
                    <span>{timeAgo(p.updated_at, i18n.language)}</span>
                  </div>
                </CardBody>
              </Card>
            </Link>
          ))}
        </div>
      )}
      <Dialog open={open} onClose={() => setOpen(false)} title={t("projects:new")} footer={<><Button variant="outline" onClick={() => setOpen(false)}>{t("common:actions.cancel")}</Button><Button form="new-project" type="submit" loading={create.isPending}>{t("common:actions.create")}</Button></>}>
        <form id="new-project" className="space-y-4" onSubmit={submit}>
          <Field label={t("projects:name")}>
            <Input required autoFocus value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Field>
          <Field label={t("projects:description")}>
            <Textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </Field>
          {create.isError && <ErrorState message={errorMessage(create.error, t)} />}
        </form>
      </Dialog>
    </>
  );
}
