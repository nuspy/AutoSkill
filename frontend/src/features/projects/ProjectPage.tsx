import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Settings } from "lucide-react";
import { useProject } from "@/api/hooks/projects";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, PageHeader, Skeleton } from "@/components/ui/misc";
import { errorMessage } from "@/lib/errors";
import { SkillsCard } from "@/features/skills/SkillsCard";

export default function ProjectPage() {
  const { projectId = "" } = useParams();
  const { t } = useTranslation(["projects", "common"]);
  const project = useProject(projectId);
  if (project.isLoading) return <Skeleton className="h-40" />;
  if (project.isError || !project.data) return <ErrorState message={errorMessage(project.error, t)} />;
  const p = project.data;
  const canEdit = p.my_role === "owner" || p.my_role === "editor";
  return (
    <>
      <PageHeader title={p.name} subtitle={p.description ?? undefined} actions={p.my_role === "owner" ? <Link to={`/p/${p.id}/settings`} className="inline-flex h-10 items-center gap-2 rounded-lg border border-border bg-card px-4 text-sm font-medium hover:bg-accent"><Settings className="h-4 w-4" />{t("projects:settings")}</Link> : undefined} />
      <div className="grid gap-4 md:grid-cols-2">
        <div className="md:col-span-2"><SkillsCard projectId={p.id} canEdit={canEdit} /></div>
        {(["trials", "runs", "pending"] as const).map((key) => (
          <Card key={key}>
            <CardHeader title={t(`projects:dashboard.${key}`)} />
            <CardBody>
              <EmptyState title={t("common:status.empty")} />
            </CardBody>
          </Card>
        ))}
      </div>
    </>
  );
}
