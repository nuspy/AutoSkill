import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useTrialActions, useTrials } from "@/api/hooks/trials";
import { useVersions } from "@/api/hooks/versions";
import type { Trial } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Badge, EmptyState, Skeleton } from "@/components/ui/misc";
import { errorMessage } from "@/lib/errors";
import { TrialLauncher } from "./TrialLauncher";
import { timeAgo } from "@/lib/format";

// A trial that is over keeps its row for as long as there is something to learn from it. Once there
// is not, it is only length: the list fills with attempts nobody will open again and the sole way to
// stop seeing one was to stop reading the list.
const CLOSED = new Set(["decided", "removed", "abandoned"]);

function TrialRow({ trial, projectId, skillId }: { trial: Trial; projectId: string; skillId: string }) {
  const { t, i18n } = useTranslation(["skills", "common"]);
  const actions = useTrialActions(trial.id);
  const [confirming, setConfirming] = useState(false);
  return (
    <li className="flex items-center gap-3 py-2 text-sm">
      <Badge tone={trial.state === "testing" ? "primary" : trial.state === "suspended" ? "warning" : "neutral"}>{t(`skills:trials.state.${trial.state}`)}</Badge>
      <Badge>{trial.target_agent}</Badge>
      <span className="flex-1 text-muted">{t(`skills:trials.purposes.${trial.purpose}`)} · {trial.corrections.length} {t("skills:trials.correctionsCount")} · {timeAgo(trial.updated_at, i18n.language)}</span>
      {/* An outcome already recorded is named in the past. The button that causes it and the badge
          that reports it were sharing one label, so a finished trial announced itself as "Remove" —
          an instruction, where what was wanted was a statement of what had happened. */}
      {trial.outcome && <Badge tone="success">{t(`skills:trials.outcomeDone.${trial.outcome}`)}</Badge>}
      <Link className="font-medium text-primary hover:underline" to={`/p/${projectId}/skills/${skillId}/trials/${trial.id}`}>{t("skills:trials.openPage")}</Link>
      {CLOSED.has(trial.state) && (
        <Button
          size="sm"
          variant="ghost"
          className="text-danger"
          title={t("skills:trials.deleteForever")}
          aria-label={t("skills:trials.deleteForever")}
          onClick={() => setConfirming(true)}
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      )}
      <Dialog
        open={confirming}
        onClose={() => setConfirming(false)}
        title={t("skills:trials.deleteForever")}
        footer={
          <>
            <Button variant="outline" onClick={() => setConfirming(false)}>{t("common:actions.cancel")}</Button>
            <Button
              className="bg-danger text-white hover:bg-danger/90"
              loading={actions.destroy.isPending}
              onClick={() =>
                actions.destroy.mutate(undefined, {
                  onSuccess: () => setConfirming(false),
                  onError: (e) => toast.error(errorMessage(e, t)),
                })
              }
            >
              {t("skills:trials.deleteForeverConfirm")}
            </Button>
          </>
        }
      >
        <p className="text-sm">{t("skills:trials.deleteForeverHelp")}</p>
      </Dialog>
    </li>
  );
}

export default function TrialsTab() {
  const { projectId = "", skillId = "" } = useParams();
  const { t } = useTranslation(["skills", "common"]);
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
            <TrialRow key={tr.id} trial={tr} projectId={projectId} skillId={skillId} />
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}
