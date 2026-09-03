import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Plus } from "lucide-react";
import { useSkills } from "@/api/hooks/skills";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge, EmptyState, Skeleton } from "@/components/ui/misc";
import { timeAgo } from "@/lib/format";

export function SkillsCard({ projectId, canEdit }: { projectId: string; canEdit: boolean }) {
  const { t, i18n } = useTranslation(["skills", "common"]);
  const skills = useSkills(projectId);
  const newLink = canEdit ? (
    <Link to={`/p/${projectId}/skills/new`} className="inline-flex h-9 items-center gap-2 rounded-lg bg-primary px-3 text-sm font-medium text-primary-fg"><Plus className="h-4 w-4" />{t("skills:new")}</Link>
  ) : undefined;
  return (
    <Card>
      <CardHeader title={t("skills:title")} actions={newLink} />
      <CardBody>
        {skills.isLoading && <Skeleton className="h-20" />}
        {skills.data && skills.data.length === 0 && <EmptyState title={t("skills:empty")} action={newLink} />}
        <ul className="divide-y divide-border">
          {skills.data?.map((s) => (
            <li key={s.id} className="py-2">
              <Link to={`/p/${projectId}/skills/${s.id}`} className="flex items-center gap-3 text-sm hover:text-primary">
                <div className="flex-1">
                  <p className="font-medium">{s.title}</p>
                  <p className="text-xs text-muted">{s.summary || s.name}</p>
                </div>
                {s.latest_interview_state && <Badge tone={s.latest_interview_state === "complete" ? "success" : s.latest_interview_state === "failed" ? "danger" : "primary"}>{t(`skills:state.${s.latest_interview_state}`)}</Badge>}
                {s.development_state === "suspended" && <Badge tone="warning">{t("skills:state.suspended")}</Badge>}
                <span className="text-xs text-muted">{timeAgo(s.updated_at, i18n.language)}</span>
              </Link>
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}
