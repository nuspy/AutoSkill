import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Copy, FlaskConical } from "lucide-react";
import { toast } from "sonner";
import { useCreateTrial } from "@/api/hooks/trials";
import { useTargets } from "@/api/hooks/versions";
import { useDevices } from "@/api/hooks/me";
import type { TrialCreated } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Select } from "@/components/ui/input";
import { ErrorState } from "@/components/ui/misc";
import { errorMessage } from "@/lib/errors";

export function TrialLauncher({ versionId, projectId, skillId, purpose = "develop", label }: { versionId: string; projectId: string; skillId: string; purpose?: "develop" | "retest" | "hub_evaluate"; label?: string }) {
  const { t } = useTranslation(["skills", "common"]);
  const navigate = useNavigate();
  const targets = useTargets();
  const devices = useDevices();
  const create = useCreateTrial();
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState("hermes");
  const [mode, setMode] = useState<"interactive" | "async">("interactive");
  const [device, setDevice] = useState<string>("");
  const [created, setCreated] = useState<TrialCreated | null>(null);
  const detected = devices.data?.flatMap((d) => d.agent_targets) ?? [];
  return (
    <>
      <Button variant={purpose === "develop" ? "primary" : "outline"} onClick={() => setOpen(true)}><FlaskConical className="h-4 w-4" />{label ?? t("skills:trials.launch")}</Button>
      <Dialog open={open} onClose={() => { setOpen(false); setCreated(null); }} title={t("skills:trials.launch")} footer={created ? <Button onClick={() => navigate(`/p/${projectId}/skills/${skillId}/trials/${created.id}`)}>{t("skills:trials.openPage")}</Button> : <><Button variant="outline" onClick={() => setOpen(false)}>{t("common:actions.cancel")}</Button><Button loading={create.isPending} onClick={() => create.mutate({ skill_version_id: versionId, target_agent: target, purpose, mode, device_id: device || null }, { onSuccess: setCreated })}>{t("skills:trials.create")}</Button></>}>
        {!created ? (
          <div className="space-y-3">
            <p className="text-sm text-muted">{t("skills:trials.intro")}</p>
            <Field label={t("skills:trials.target")}>
              <Select value={target} onChange={(e) => setTarget(e.target.value)}>
                {targets.data?.map((tg) => <option key={tg.id} value={tg.id}>{tg.display_name}{detected.includes(tg.id) ? " ✓" : ""}</option>)}
              </Select>
            </Field>
            <Field label={t("skills:trials.device")}>
              <Select value={device} onChange={(e) => setDevice(e.target.value)}>
                <option value="">{t("skills:trials.anyDevice")}</option>
                {devices.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </Select>
            </Field>
            <Field label={t("skills:trials.mode")} hint={t(`skills:trials.modeHint.${mode}`)}>
              <Select value={mode} onChange={(e) => setMode(e.target.value as "interactive" | "async")}>
                <option value="interactive">{t("skills:trials.modes.interactive")}</option>
                <option value="async">{t("skills:trials.modes.async")}</option>
              </Select>
            </Field>
            {create.isError && <ErrorState message={errorMessage(create.error, t)} />}
          </div>
        ) : (
          <div className="space-y-3 text-sm">
            <p>{t("skills:trials.createdHelp")}</p>
            <div className="flex items-start gap-2">
              <pre className="flex-1 overflow-x-auto rounded-lg bg-accent p-3 font-mono text-xs">{created.cli_command}</pre>
              <Button size="icon" variant="outline" aria-label={t("common:actions.copy")} onClick={() => { navigator.clipboard.writeText(created.cli_command); toast.success(t("common:actions.copied")); }}><Copy className="h-4 w-4" /></Button>
            </div>
            <p className="text-xs text-muted">{t("skills:trials.tokenWarning")}</p>
          </div>
        )}
      </Dialog>
    </>
  );
}
