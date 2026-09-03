import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { useVersionLifecycle, useVersionTransitions } from "@/api/hooks/review";
import type { SkillVersionDetail } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Textarea } from "@/components/ui/input";
import { Badge } from "@/components/ui/misc";
import { errorMessage } from "@/lib/errors";
import { timeAgo } from "@/lib/format";

const PUBLISH_CHECKS = ["reviewed_diff", "trial_accepted", "install_docs_checked"];
const DEPRECATE_CHECKS = ["installers_notified"];

export function LifecyclePanel({ version, canEdit }: { version: SkillVersionDetail; canEdit: boolean }) {
  const { t, i18n } = useTranslation(["skills", "common"]);
  const lifecycle = useVersionLifecycle(version.id, version.skill_id);
  const transitions = useVersionTransitions(version.id);
  const [dialog, setDialog] = useState<"submit" | "publish" | "deprecate" | null>(null);
  const [text, setText] = useState("");
  const [checks, setChecks] = useState<Record<string, boolean>>({});
  const onError = (e: unknown) => toast.error(errorMessage(e, t));
  const close = () => { setDialog(null); setText(""); setChecks({}); };
  const allConfirmed = version.steps.length > 0 && version.steps.every((s) => s.test_status === "confirmed" || s.test_status === "corrected");
  const checkKeys = dialog === "publish" ? PUBLISH_CHECKS : DEPRECATE_CHECKS;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {canEdit && version.state === "testing" && allConfirmed && <Button size="sm" onClick={() => lifecycle.transition.mutate({ to_state: "tested" }, { onError })}>{t("skills:lifecycle.markTested")}</Button>}
        {canEdit && (version.state === "tested" || version.state === "changes_requested") && <Button size="sm" onClick={() => setDialog("submit")}>{t("skills:lifecycle.submitReview")}</Button>}
        {canEdit && (version.state === "tested" || version.state === "changes_requested") && <Button size="sm" variant="outline" onClick={() => lifecycle.transition.mutate({ to_state: "testing" }, { onError })}>{t("skills:lifecycle.backToTesting")}</Button>}
        {canEdit && version.state === "approved" && <Button size="sm" onClick={() => setDialog("publish")}>{t("skills:lifecycle.publish")}</Button>}
        {canEdit && version.state === "published" && <Button size="sm" variant="outline" onClick={() => setDialog("deprecate")}>{t("skills:lifecycle.deprecate")}</Button>}
        {version.state === "submitted_for_review" && <Badge tone="warning">{t("skills:lifecycle.waitingReview")}</Badge>}
      </div>
      {transitions.data && transitions.data.length > 0 && (
        <ol className="space-y-1 text-xs text-muted">
          {transitions.data.slice().reverse().map((tr) => (
            <li key={tr.id} className="flex items-center gap-2"><Badge>{t(`skills:versions.state.${tr.to_state}`, { defaultValue: tr.to_state })}</Badge><span>{tr.actor_user_id ? t("skills:lifecycle.byPerson") : t("skills:lifecycle.bySystem")}{tr.reason ? ` · ${tr.reason}` : ""}</span><span className="ml-auto">{timeAgo(tr.created_at, i18n.language)}</span></li>
          ))}
        </ol>
      )}
      <Dialog open={dialog === "submit"} onClose={close} title={t("skills:lifecycle.submitReview")} footer={<><Button variant="outline" onClick={close}>{t("common:actions.cancel")}</Button><Button loading={lifecycle.submit.isPending} onClick={() => lifecycle.submit.mutate(text || undefined, { onSuccess: () => { close(); toast.success(t("skills:lifecycle.submitted")); }, onError })}>{t("common:actions.confirm")}</Button></>}>
        <p className="mb-3 text-sm text-muted">{t("skills:lifecycle.submitHelp")}</p>
        <Field label={t("skills:lifecycle.summary")}><Textarea rows={4} value={text} onChange={(e) => setText(e.target.value)} /></Field>
      </Dialog>
      <Dialog open={dialog === "publish" || dialog === "deprecate"} onClose={close} title={dialog === "publish" ? t("skills:lifecycle.publish") : t("skills:lifecycle.deprecate")} footer={<><Button variant="outline" onClick={close}>{t("common:actions.cancel")}</Button><Button variant={dialog === "deprecate" ? "danger" : "primary"} disabled={!checkKeys.every((k) => checks[k])} loading={lifecycle.authorize.isPending} onClick={() => lifecycle.authorize.mutate({ action: dialog as "publish" | "deprecate", checklist: checks, comment: text || undefined }, { onSuccess: () => { close(); toast.success(t("skills:lifecycle.authorized")); }, onError })}>{t("skills:lifecycle.authorize")}</Button></>}>
        <p className="mb-3 text-sm text-muted">{t(`skills:lifecycle.${dialog === "publish" ? "publishHelp" : "deprecateHelp"}`)}</p>
        <ul className="mb-3 space-y-2 text-sm">
          {checkKeys.map((k) => <li key={k}><label className="flex items-center gap-2"><input type="checkbox" checked={!!checks[k]} onChange={(e) => setChecks({ ...checks, [k]: e.target.checked })} />{t(`skills:lifecycle.checks.${k}`)}</label></li>)}
        </ul>
        <Field label={t("skills:review.comment")}><Textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} /></Field>
      </Dialog>
    </div>
  );
}
