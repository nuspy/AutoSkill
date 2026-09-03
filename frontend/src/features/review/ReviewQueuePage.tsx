import { useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useReviewQueue } from "@/api/hooks/review";
import { useSession } from "@/stores/session";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge, EmptyState, PageHeader, Skeleton } from "@/components/ui/misc";
import { timeAgo } from "@/lib/format";

export default function ReviewQueuePage() {
  const { t, i18n } = useTranslation(["skills", "common"]);
  const user = useSession((s) => s.user);
  const [mine, setMine] = useState(false);
  const queue = useReviewQueue(!!user && (user.role === "admin" || user.role === "reviewer"), mine);
  return (
    <>
      <PageHeader title={t("skills:review.queue")} subtitle={t("skills:review.queueHelp")} actions={<Button variant={mine ? "secondary" : "outline"} onClick={() => setMine(!mine)}>{t("skills:review.assignedToMe")}</Button>} />
      {queue.isLoading && <Skeleton className="h-24" />}
      {queue.data && queue.data.length === 0 && <EmptyState title={t("skills:review.empty")} />}
      {queue.data && queue.data.length > 0 && (
        <Card>
          <ul className="divide-y divide-border">
            {queue.data.map((r) => (
              <li key={r.id} className="flex items-center gap-3 px-5 py-3 text-sm">
                <Badge tone={r.state === "in_review" ? "primary" : "warning"}>{t(`skills:review.state.${r.state}`)}</Badge>
                <div className="flex-1">
                  <p className="font-medium">{r.skill_title} <span className="font-mono text-muted">v{r.version}</span></p>
                  <p className="text-xs text-muted">{r.requested_by_name} · {timeAgo(r.created_at, i18n.language)}{r.summary ? ` · ${r.summary}` : ""}</p>
                </div>
                <span className="text-xs text-muted">{String(r.checklist.steps_confirmed ?? 0)}/{String(r.checklist.steps_total ?? 0)} ✓ · {String(r.checklist.trials_accepted ?? 0)} {t("skills:review.trialsAccepted")}</span>
                <Link className="font-medium text-primary hover:underline" to={`/review/${r.id}`}>{t("skills:review.open")}</Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}
