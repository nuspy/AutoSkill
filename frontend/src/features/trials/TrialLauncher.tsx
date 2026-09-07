import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { FlaskConical } from "lucide-react";
import { useCreateTrial } from "@/api/hooks/trials";
import { useTargets } from "@/api/hooks/versions";
import { useDevices } from "@/api/hooks/me";
import type { TrialCreated } from "@/api/types";
import { Button } from "@/components/ui/button";
import { CopyRow } from "@/components/ui/copy-row";
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
  const [chosen, setChosen] = useState<string | null>(null);
  const [mode, setMode] = useState<"interactive" | "async">("interactive");
  const [device, setDevice] = useState<string>("");
  const [autoConfirm, setAutoConfirm] = useState(true);
  const [created, setCreated] = useState<TrialCreated | null>(null);
  const detected = devices.data?.flatMap((d) => d.agent_targets) ?? [];
  // Default to an agent this machine actually reports. A fixed default installed the trial into
  // the folder of an agent that was not there: the copy landed where nothing would ever look for
  // it, the trial stayed `installed` for ever, and the page could only say it was waiting.
  const target = chosen ?? detected[0] ?? targets.data?.[0]?.id ?? "";
  const targetMissing = !!target && detected.length > 0 && !detected.includes(target);
  return (
    <>
      {/* The label is a sentence, not a word, and it sits in a flex row beside other buttons: without
          `shrink-0` the row squeezes it and without `whitespace-nowrap` it breaks mid-phrase, which is
          how the text ended up outside its own button. `px-6` gives it half again the usual breathing
          room, so the longest translation still sits comfortably inside. */}
      <Button
        variant={purpose === "develop" ? "primary" : "outline"}
        onClick={() => setOpen(true)}
        className="shrink-0 whitespace-nowrap px-6"
      >
        <FlaskConical className="h-4 w-4" />
        {label ?? t("skills:trials.launch")}
      </Button>
      <Dialog open={open} onClose={() => { setOpen(false); setCreated(null); }} title={t("skills:trials.launch")} footer={created ? <Button onClick={() => navigate(`/p/${projectId}/skills/${skillId}/trials/${created.id}`)}>{t("skills:trials.openPage")}</Button> : <><Button variant="outline" onClick={() => setOpen(false)}>{t("common:actions.cancel")}</Button><Button loading={create.isPending} onClick={() => create.mutate({ skill_version_id: versionId, target_agent: target, purpose, mode, device_id: device || null, auto_confirm: autoConfirm }, { onSuccess: setCreated })}>{t("skills:trials.create")}</Button></>}>
        {!created ? (
          <div className="space-y-3">
            <p className="text-sm text-muted">{t("skills:trials.intro")}</p>
            <Field label={t("skills:trials.target")}>
              <Select value={target} onChange={(e) => setChosen(e.target.value)}>
                {targets.data?.map((tg) => <option key={tg.id} value={tg.id}>{tg.display_name}{detected.includes(tg.id) ? " ✓" : ""}</option>)}
              </Select>
            </Field>
            {targetMissing && (
              <p className="rounded-lg bg-warning/10 px-3 py-2 text-sm text-warning">{t("skills:trials.targetNotDetected")}</p>
            )}
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
            <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={autoConfirm} onChange={(e) => setAutoConfirm(e.target.checked)} /><span>{t("skills:trials.autoConfirm")}<span className="block text-xs text-muted">{t("skills:trials.autoConfirmHint")}</span></span></label>
            {create.isError && <ErrorState message={errorMessage(create.error, t)} />}
          </div>
        ) : (
          <div className="space-y-3 text-sm">
            <p>{t("skills:trials.createdHelp")}</p>
            <CopyRow label={t("skills:trials.cliCommand")} value={created.cli_command} hint={t("skills:trials.tokenWarning")} />
            {created.bundle_url && (
              <>
                <CopyRow label={t("skills:trials.bundleUrl")} value={created.bundle_url} hint={t("skills:trials.bundleUrlHint")} />
                {/* The instruction carries the trial token, like the CLI command above it: an agent
                    told to install this trial needs it, and telling it to "ask me" for a value the
                    person will not have once this dialog closes only moves the dead end. */}
                <CopyRow label={t("skills:trials.tellAgent")} value={t("skills:trials.tellAgentText", { url: created.bundle_url, manifest: created.manifest_url ?? "", token: created.session_token })} hint={t("skills:trials.tokenWarning")} />
              </>
            )}
          </div>
        )}
      </Dialog>
    </>
  );
}
