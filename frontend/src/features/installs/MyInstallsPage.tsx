import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Trash2 } from "lucide-react";
import { useInstallationMutations, useInstallations } from "@/api/hooks/hub";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge, EmptyState, PageHeader, Skeleton } from "@/components/ui/misc";
import { timeAgo } from "@/lib/format";

export default function MyInstallsPage() {
  const { t, i18n } = useTranslation(["skills", "common"]);
  const installs = useInstallations();
  const { remove } = useInstallationMutations();
  return (
    <>
      <PageHeader title={t("skills:installs.title")} subtitle={t("skills:installs.subtitle")} />
      {installs.isLoading && <Skeleton className="h-24" />}
      {installs.data && installs.data.length === 0 && <EmptyState title={t("skills:installs.empty")} action={<Link className="text-primary hover:underline" to="/hub">{t("nav.hub", { ns: "common" })}</Link>} />}
      {installs.data && installs.data.length > 0 && (
        <Card>
          <ul className="divide-y divide-border">
            {installs.data.map((i) => (
              <li key={i.id} className="flex items-center gap-3 px-5 py-3 text-sm">
                <div className="flex-1">
                  <Link className="font-medium hover:text-primary" to={`/hub/s/${i.skill_id}`}>{i.skill_title}</Link>
                  <p className="text-xs text-muted">v{i.installed_version} · {i.target_agent} · {t(`skills:installs.state.${i.state}`)} · {i.run_count} {t("skills:runs.title").toLowerCase()} · {timeAgo(i.updated_at, i18n.language)}</p>
                </div>
                {i.kind === "trial" && <Badge tone="warning">{t("skills:trials.title")}</Badge>}
                {i.update_available && <Badge tone="warning">{t("skills:installs.update", { version: i.latest_version })}</Badge>}
                {i.update_available && <code className="rounded bg-accent px-1.5 py-0.5 text-xs">autoskill install --version-id {i.latest_version_id} --target {i.target_agent}</code>}
                <Button size="icon" variant="ghost" aria-label={t("common:actions.remove")} onClick={() => remove.mutate(i.id)}><Trash2 className="h-4 w-4 text-danger" /></Button>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}
