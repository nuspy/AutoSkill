import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useTrials } from "@/api/hooks/trials";
import { Card } from "@/components/ui/card";
import { Badge, EmptyState, PageHeader, Skeleton } from "@/components/ui/misc";
import { timeAgo } from "@/lib/format";

export default function MyTrialsPage() {
  const { t, i18n } = useTranslation(["skills", "common"]);
  const trials = useTrials(undefined, false);
  return (
    <>
      <PageHeader title={t("skills:trials.mine")} subtitle={t("skills:trials.mineHelp")} />
      {trials.isLoading && <Skeleton className="h-24" />}
      {trials.data && trials.data.length === 0 && <EmptyState title={t("skills:trials.none")} />}
      {trials.data && trials.data.length > 0 && (
        <Card>
          <ul className="divide-y divide-border">
            {trials.data.map((tr) => (
              <li key={tr.id} className="flex items-center gap-3 px-5 py-3 text-sm">
                <Badge tone={tr.state === "testing" ? "primary" : tr.state === "suspended" ? "warning" : "neutral"}>{t(`skills:trials.state.${tr.state}`)}</Badge>
                <Badge>{tr.target_agent}</Badge>
                <span className="flex-1 text-muted">{t(`skills:trials.purposes.${tr.purpose}`)} · {timeAgo(tr.updated_at, i18n.language)}</span>
                {tr.outcome && <Badge tone="success">{t(`skills:trials.outcomes.${tr.outcome}`)}</Badge>}
                <Link className="font-medium text-primary hover:underline" to={`/p/${tr.project_id}/skills/${tr.skill_id}/trials/${tr.id}`}>{t("skills:trials.openPage")}</Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}
