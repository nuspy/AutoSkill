import { useState } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Download, FileCode2, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { downloadZip, useDiscardVersion, useGenerateVersion, useVersion, useVersionFile, useVersions } from "@/api/hooks/versions";
import { useSkill } from "@/api/hooks/skills";
import type { StepDefinition } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Textarea } from "@/components/ui/input";
import { Markdown } from "@/components/ui/markdown";
import { Badge, EmptyState, ErrorState, Skeleton } from "@/components/ui/misc";
import { InstallGuide } from "./InstallGuide";
import { TrialLauncher } from "@/features/trials/TrialLauncher";
import { errorMessage } from "@/lib/errors";
import { timeAgo } from "@/lib/format";
import { cn } from "@/lib/cn";

const STATE_TONE: Record<string, "neutral" | "primary" | "success" | "warning" | "danger"> = {
  draft: "neutral", testing: "primary", tested: "primary", submitted_for_review: "warning", approved: "success", changes_requested: "warning",
  rejected: "danger", published: "success", superseded: "neutral", deprecated: "danger", discarded: "neutral",
};

export default function VersionsTab() {
  const { skillId = "" } = useParams();
  const { t } = useTranslation(["skills", "common"]);
  const skill = useSkill(skillId);
  const versions = useVersions(skillId);
  const generate = useGenerateVersion(skillId);
  const discard = useDiscardVersion(skillId);
  const [selected, setSelected] = useState<string | null>(null);
  const [genOpen, setGenOpen] = useState(false);
  const [instructions, setInstructions] = useState("");
  const current = selected ?? versions.data?.[0]?.id ?? null;
  const canGenerate = skill.data?.latest_interview_state === "complete" || skill.data?.latest_interview_state === "drafting_requested" || (versions.data?.length ?? 0) > 0;

  if (versions.isLoading) return <Skeleton className="h-40" />;
  return (
    <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
      <div className="space-y-3">
        <Button className="w-full" disabled={!canGenerate} loading={generate.isPending} onClick={() => setGenOpen(true)}><RefreshCw className="h-4 w-4" />{versions.data?.length ? t("skills:versions.regenerate") : t("skills:versions.generate")}</Button>
        {!canGenerate && <p className="text-xs text-muted">{t("skills:versions.needInterview")}</p>}
        {versions.data?.length === 0 && <EmptyState title={t("skills:versions.empty")} />}
        <ul className="space-y-1">
          {versions.data?.map((v) => (
            <li key={v.id}>
              <button className={cn("w-full rounded-lg border px-3 py-2 text-left text-sm", current === v.id ? "border-primary bg-primary/5" : "border-border hover:bg-accent")} onClick={() => setSelected(v.id)}>
                <div className="flex items-center justify-between"><span className="font-mono font-medium">v{v.version}</span><Badge tone={STATE_TONE[v.state] ?? "neutral"}>{t(`skills:versions.state.${v.state}`, { defaultValue: v.state })}</Badge></div>
                <p className="mt-0.5 truncate text-xs text-muted">{v.changelog || t(`skills:versions.origin.${v.origin}`, { defaultValue: v.origin })}</p>
              </button>
            </li>
          ))}
        </ul>
      </div>
      {current ? <VersionDetail versionId={current} skillName={skill.data?.name ?? "skill"} onDiscard={(id) => discard.mutate(id, { onSuccess: () => { setSelected(null); toast.success(t("skills:versions.discarded")); } })} /> : <EmptyState title={t("common:status.empty")} />}
      <Dialog open={genOpen} onClose={() => setGenOpen(false)} title={t("skills:versions.generate")} footer={<><Button variant="outline" onClick={() => setGenOpen(false)}>{t("common:actions.cancel")}</Button><Button loading={generate.isPending} onClick={() => generate.mutate({ mode: versions.data?.length ? "patch" : "new", instructions: instructions || undefined }, { onSuccess: () => { setGenOpen(false); toast.success(t("skills:versions.generating")); }, onError: (e) => toast.error(errorMessage(e, t)) })}>{t("common:actions.confirm")}</Button></>}>
        <Field label={t("skills:versions.instructions")}><Textarea rows={4} value={instructions} onChange={(e) => setInstructions(e.target.value)} placeholder={t("skills:versions.instructionsPlaceholder")} /></Field>
      </Dialog>
    </div>
  );
}

function VersionDetail({ versionId, skillName, onDiscard }: { versionId: string; skillName: string; onDiscard: (id: string) => void }) {
  const { t, i18n } = useTranslation(["skills", "common"]);
  const { projectId = "", skillId = "" } = useParams();
  const version = useVersion(versionId);
  const [tab, setTab] = useState<"steps" | "files" | "install">("steps");
  const [file, setFile] = useState<string>("SKILL.md");
  const content = useVersionFile(versionId, tab === "files" ? file : null);
  if (version.isLoading || !version.data) return <Skeleton className="h-64" />;
  const v = version.data;
  const discardable = ["draft", "testing", "tested", "changes_requested"].includes(v.state);
  return (
    <Card>
      <CardHeader
        title={<span className="font-mono">v{v.version}</span>}
        description={`${t(`skills:versions.origin.${v.origin}`, { defaultValue: v.origin })} · ${timeAgo(v.created_at, i18n.language)}${v.changelog ? ` · ${v.changelog}` : ""}`}
        actions={
          <div className="flex gap-2">
            {["draft", "testing", "tested", "approved", "published"].includes(v.state) && <TrialLauncher versionId={v.id} projectId={projectId} skillId={skillId} purpose={v.state === "draft" || v.state === "testing" ? "develop" : "retest"} label={v.state === "draft" || v.state === "testing" ? undefined : t("skills:trials.retest")} />}
            <Button size="sm" variant="outline" onClick={() => downloadZip(v.id, `${skillName}-${v.version}.zip`, ["hermes", "openclaw"]).catch(() => toast.error(t("common:errors.generic")))}><Download className="h-4 w-4" />{t("skills:versions.download")}</Button>
            {discardable && <Button size="sm" variant="ghost" onClick={() => onDiscard(v.id)}><Trash2 className="h-4 w-4 text-danger" /></Button>}
          </div>
        }
      />
      <div className="flex gap-1 border-b border-border px-5">
        {(["steps", "files", "install"] as const).map((k) => (
          <button key={k} className={cn("border-b-2 px-3 py-2 text-sm font-medium", tab === k ? "border-primary text-primary" : "border-transparent text-muted")} onClick={() => setTab(k)}>{t(`skills:versions.tabs.${k}`)}</button>
        ))}
      </div>
      <CardBody>
        {!v.validation_report.ok && <ErrorState message={v.validation_report.issues.filter((i) => i.level === "error").map((i) => i.message).join("; ")} />}
        {tab === "steps" && <StepList steps={v.steps} dependencies={v.dependencies} />}
        {tab === "files" && (
          <div className="grid gap-4 md:grid-cols-[200px_1fr]">
            <ul className="space-y-1 text-sm">
              {v.manifest.files.map((f) => (
                <li key={f.path}><button className={cn("flex w-full items-center gap-2 rounded px-2 py-1 text-left", file === f.path ? "bg-primary/10 text-primary" : "hover:bg-accent")} onClick={() => setFile(f.path)}><FileCode2 className="h-3.5 w-3.5" /><span className="truncate">{f.path}</span></button></li>
              ))}
            </ul>
            <div className="min-w-0">
              {content.data ? (file.endsWith(".md") ? <Markdown source={content.data.content} /> : <pre className="overflow-x-auto rounded-lg bg-accent p-3 text-xs">{content.data.content}</pre>) : <Skeleton className="h-40" />}
            </div>
          </div>
        )}
        {tab === "install" && <InstallGuide versionId={v.id} />}
      </CardBody>
    </Card>
  );
}

function StepList({ steps, dependencies }: { steps: StepDefinition[]; dependencies: { component_slug: string; reason: string | null }[] }) {
  const { t } = useTranslation(["skills"]);
  return (
    <div className="space-y-3">
      {dependencies.length > 0 && <p className="text-sm text-muted">{t("skills:versions.dependsOn")}: {dependencies.map((d) => <Badge key={d.component_slug} tone="primary" className="mr-1">{d.component_slug}</Badge>)}</p>}
      <ol className="space-y-2">
        {steps.map((s) => (
          <li key={s.id} className="rounded-lg border border-border p-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{s.ordinal}. {s.title}</span>
              <code className="text-xs text-muted">{s.key}</code>
              <Badge>{t(`skills:knowledge.kind.${s.kind}`)}</Badge>
              <Badge tone={s.side_effects === "irreversible" ? "danger" : s.side_effects === "reversible" ? "warning" : s.side_effects === "read_only" ? "success" : "neutral"}>{t(`skills:knowledge.sideEffects.${s.side_effects}`)}</Badge>
              <Badge tone="neutral">{t(`skills:versions.trialMode.${s.trial_mode}`)}</Badge>
              {s.requires_explicit_auth && <Badge tone="danger">{t("skills:versions.explicitAuth")}</Badge>}
              {s.library_component_slug && <Badge tone="primary">{s.library_component_slug}</Badge>}
              <Badge tone={s.test_status === "confirmed" ? "success" : "neutral"} className="ml-auto">{t(`skills:versions.testStatus.${s.test_status}`)}</Badge>
            </div>
            <p className="mt-1 whitespace-pre-wrap text-muted">{s.instruction}</p>
            {s.success_criteria && <p className="mt-1 text-xs"><span className="font-medium">{t("skills:versions.doneWhen")}:</span> {s.success_criteria}</p>}
          </li>
        ))}
      </ol>
    </div>
  );
}
