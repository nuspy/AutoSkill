import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useTrials } from "@/api/hooks/trials";
import { useVersions } from "@/api/hooks/versions";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge, EmptyState, Skeleton } from "@/components/ui/misc";
import { TrialLauncher } from "./TrialLauncher";
import { timeAgo } from "@/lib/format";

export default function TrialsTab() {
  const { projectId = "", skillId = "" } = useParams();
  const { t, i18n } = useTranslation(["skills", "common"]);
  const trials = useTrials(skillId);
  const versions = useVersions(skillId);
  const testable = versions.data?.find((v) => ["draft", "testing", "tested", "published", "approved"].includes(v.state));
  return (
    <Card>
      <CardHeader title={t("skills:trials.title")} description={t("skills:trials.subtitle")} actions={testable ? <TrialLauncher versionId={testable.id} projectId={projectId} skillId={skillId} purpose={testable.state === "tested" || testable.state === "published" ? "retest" : "develop"} label={testable.state === "tested" || testable.state === "published" ? t("skills:trials.retest") : undefined} /> : undefined} />
      <CardBody>
        {trials.isLoading && <Skeleton className="h-20" />}
        {trials.data && trials.data.length === 0 && <EmptyState title={t("skills:trials.none")} description={t("skills:trials.noneHelp")} />}
        <ul className="divide-y divide-border">
          {trials.data?.map((tr) => (
            <li key={tr.id} className="flex items-center gap-3 py-2 text-sm">
              <Badge tone={tr.state === "testing" ? "primary" : tr.state === "suspended" ? "warning" : "neutral"}>{t(`skills:trials.state.${tr.state}`)}</Badge>
              <Badge>{tr.target_agent}</Badge>
              <span className="flex-1 text-muted">{t(`skills:trials.purposes.${tr.purpose}`)} · {tr.corrections.length} {t("skills:trials.correctionsCount")} · {timeAgo(tr.updated_at, i18n.language)}</span>
              {tr.outcome && <Badge tone="success">{t(`skills:trials.outcomes.${tr.outcome}`)}</Badge>}
              <Link className="font-medium text-primary hover:underline" to={`/p/${projectId}/skills/${skillId}/trials/${tr.id}`}>{t("skills:trials.openPage")}</Link>
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}
