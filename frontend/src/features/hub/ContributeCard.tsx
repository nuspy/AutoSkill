import { useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { GitPullRequestArrow } from "lucide-react";
import { toast } from "sonner";
import { useContributionMutations, useContributions } from "@/api/hooks/hub";
import type { Skill } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Textarea } from "@/components/ui/input";
import { Badge } from "@/components/ui/misc";
import { errorMessage } from "@/lib/errors";

/** On a variant: propose changes to the original. On any skill: decide on received contributions. */
export function ContributeCard({ skill, canEdit }: { skill: Skill; canEdit: boolean }) {
  const { t } = useTranslation(["skills", "common"]);
  const contributions = useContributions(skill.id);
  const { contribute, decide } = useContributionMutations(skill.id);
  const [message, setMessage] = useState("");
  const isFork = !!skill.forked_from_skill_id;
  const received = contributions.data?.filter((c) => c.target_skill_id === skill.id) ?? [];
  const sent = contributions.data?.filter((c) => c.source_skill_id === skill.id) ?? [];
  if (!isFork && received.length === 0) return null;
  return (
    <Card>
      <CardHeader title={t("skills:hub.contribute.title")} description={isFork ? t("skills:hub.contribute.help") : t("skills:hub.contribute.receivedHelp")} />
      <CardBody className="space-y-3 text-sm">
        {isFork && canEdit && (
          <div className="space-y-2">
            <Field label={t("skills:hub.contribute.message")}><Textarea rows={2} value={message} onChange={(e) => setMessage(e.target.value)} /></Field>
            <Button loading={contribute.isPending} onClick={() => contribute.mutate({ message: message || undefined }, { onSuccess: () => { setMessage(""); toast.success(t("skills:hub.contribute.sent")); }, onError: (e) => toast.error(errorMessage(e, t)) })}><GitPullRequestArrow className="h-4 w-4" />{t("skills:hub.contribute.action")}</Button>
          </div>
        )}
        {[...received, ...sent].map((c) => (
          <div key={c.id} className="rounded-lg border border-border p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={c.state === "accepted" ? "success" : c.state === "rejected" ? "danger" : "warning"}>{t(`skills:hub.contribute.state.${c.state}`)}</Badge>
              <span className="font-medium">{c.source_title} v{c.source_version}</span>
              <span className="text-xs text-muted">→ {c.target_title} · {c.proposed_by_name}</span>
            </div>
            {c.message && <p className="mt-1 text-muted">{c.message}</p>}
            {c.decision_comment && <p className="mt-1 text-xs text-muted">{c.decision_comment}</p>}
            {c.state === "open" && c.target_skill_id === skill.id && canEdit && (
              <div className="mt-2 flex gap-2">
                <Button size="sm" loading={decide.isPending} onClick={() => decide.mutate({ id: c.id, accept: true }, { onSuccess: () => toast.success(t("skills:hub.contribute.accepted")), onError: (e) => toast.error(errorMessage(e, t)) })}>{t("skills:hub.contribute.accept")}</Button>
                <Button size="sm" variant="outline" onClick={() => decide.mutate({ id: c.id, accept: false })}>{t("skills:hub.contribute.reject")}</Button>
              </div>
            )}
            {c.state === "accepted" && c.target_version_id && c.target_skill_id === skill.id && <Link className="mt-2 block text-xs text-primary hover:underline" to={`/p/${skill.project_id}/skills/${skill.id}/versions`}>{t("skills:hub.contribute.draftCreated")}</Link>}
          </div>
        ))}
      </CardBody>
    </Card>
  );
}
