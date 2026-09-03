import { useState } from "react";
import { NavLink, Navigate, Route, Routes, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { PauseCircle, PlayCircle } from "lucide-react";
import { useInterviews, useSkill, useSuspendResumeSkill } from "@/api/hooks/skills";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Textarea } from "@/components/ui/input";
import { Badge, EmptyState, ErrorState, PageHeader, Skeleton } from "@/components/ui/misc";
import { errorMessage } from "@/lib/errors";
import { cn } from "@/lib/cn";
import { KnowledgePanel } from "@/features/interview/KnowledgePanel";
import { useKnowledgeHistory } from "@/api/hooks/skills";
import MemoryTab from "@/features/memory/MemoryTab";
import InterviewPage from "@/features/interview/InterviewPage";
import VersionsTab from "@/features/versions/VersionsTab";
import TrialsTab from "@/features/trials/TrialsTab";
import TrialPage from "@/features/trials/TrialPage";
import RunsTab from "@/features/runs/RunsTab";
import { Link } from "react-router-dom";
import { timeAgo } from "@/lib/format";
import { PublishSettingsCard } from "@/features/hub/PublishSettingsCard";

const TABS = ["overview", "interview", "knowledge", "memory", "versions", "trials", "runs"] as const;

export default function SkillPage() {
  const { projectId = "", skillId = "" } = useParams();
  const { t, i18n } = useTranslation(["skills", "common"]);
  const skill = useSkill(skillId);
  const toggle = useSuspendResumeSkill(skillId);
  const [suspendOpen, setSuspendOpen] = useState(false);
  const [note, setNote] = useState("");

  if (skill.isLoading) return <Skeleton className="h-40" />;
  if (skill.isError || !skill.data) return <ErrorState message={errorMessage(skill.error, t)} />;
  const s = skill.data;
  const suspended = s.development_state === "suspended";
  return (
    <>
      <PageHeader
        title={s.title}
        subtitle={s.summary ?? undefined}
        actions={
          suspended ? (
            <Button variant="outline" loading={toggle.isPending} onClick={() => toggle.mutate({ action: "resume" })}><PlayCircle className="h-4 w-4" />{t("skills:suspend.resume")}</Button>
          ) : (
            <Button variant="outline" onClick={() => setSuspendOpen(true)}><PauseCircle className="h-4 w-4" />{t("skills:suspend.action")}</Button>
          )
        }
      />
      {suspended && <div className="mb-4 rounded-lg border border-warning/40 bg-warning/10 px-4 py-2 text-sm">{t("skills:suspend.banner", { note: s.suspend_note ?? "" })}</div>}
      <div className="mb-4 flex items-center gap-2 text-xs text-muted">
        <code className="rounded bg-accent px-1.5 py-0.5">{s.name}</code>
        <Badge tone={suspended ? "warning" : "primary"}>{t(`skills:state.${s.development_state}`)}</Badge>
        <span>· {timeAgo(s.updated_at, i18n.language)}</span>
      </div>
      <nav className="mb-6 flex gap-1 border-b border-border">
        {TABS.map((tab) => (
          <NavLink key={tab} to={`/p/${projectId}/skills/${skillId}/${tab}`} className={({ isActive }) => cn("border-b-2 px-3 py-2 text-sm font-medium", isActive ? "border-primary text-primary" : "border-transparent text-muted hover:text-fg")}>{t(`skills:tabs.${tab}`)}</NavLink>
        ))}
      </nav>
      <Routes>
        <Route index element={<Navigate to="overview" replace />} />
        <Route path="overview" element={<OverviewTab />} />
        <Route path="interview" element={<InterviewListTab />} />
        <Route path="interview/:sessionId" element={<InterviewPage />} />
        <Route path="knowledge" element={<KnowledgeTab />} />
        <Route path="memory" element={<MemoryTab skillId={skillId} />} />
        <Route path="versions" element={<VersionsTab />} />
        <Route path="trials" element={<TrialsTab />} />
        <Route path="trials/:trialId" element={<TrialPage />} />
        <Route path="runs" element={<RunsTab />} />
      </Routes>
      <Dialog open={suspendOpen} onClose={() => setSuspendOpen(false)} title={t("skills:suspend.action")} footer={<><Button variant="outline" onClick={() => setSuspendOpen(false)}>{t("common:actions.cancel")}</Button><Button loading={toggle.isPending} onClick={() => toggle.mutate({ action: "suspend", note }, { onSuccess: () => setSuspendOpen(false) })}>{t("common:actions.confirm")}</Button></>}>
        <Field label={t("skills:suspend.note")}><Textarea value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </Dialog>
    </>
  );
}

function OverviewTab() {
  const { projectId = "", skillId = "" } = useParams();
  const { t } = useTranslation(["skills", "common"]);
  const skill = useSkill(skillId);
  const history = useKnowledgeHistory(skillId);
  const latest = history.data?.[0];
  const s = skill.data!;
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div className="md:col-span-2"><PublishSettingsCard skill={s} canEdit /></div>
      <Card>
        <CardHeader title={t("skills:tabs.interview")} />
        <CardBody>
          {s.latest_interview_id ? (
            <p className="text-sm">
              <Badge tone={s.latest_interview_state === "complete" ? "success" : s.latest_interview_state === "failed" ? "danger" : "primary"}>{t(`skills:state.${s.latest_interview_state}`)}</Badge>
              <Link className="ml-3 font-medium text-primary hover:underline" to={`/p/${projectId}/skills/${skillId}/interview/${s.latest_interview_id}`}>{t("skills:interview.resume")}</Link>
            </p>
          ) : (
            <EmptyState title={t("common:status.empty")} />
          )}
        </CardBody>
      </Card>
      <Card>
        <CardHeader title={t("skills:knowledge.title")} />
        <CardBody>
          {latest ? <p className="text-sm">{t("skills:knowledge.completeness", { passed: latest.completeness.passed, total: latest.completeness.total })} · {t("skills:knowledge.revision", { n: latest.revision })}</p> : <EmptyState title={t("common:status.empty")} />}
        </CardBody>
      </Card>
    </div>
  );
}

function InterviewListTab() {
  const { projectId = "", skillId = "" } = useParams();
  const { t, i18n } = useTranslation(["skills", "common"]);
  const sessions = useInterviews(projectId, skillId);
  if (sessions.isLoading) return <Skeleton className="h-24" />;
  if (!sessions.data?.length) return <EmptyState title={t("common:status.empty")} />;
  return (
    <Card>
      <ul className="divide-y divide-border">
        {sessions.data.map((s) => (
          <li key={s.id} className="flex items-center gap-3 px-5 py-3 text-sm">
            <Badge tone={s.state === "complete" ? "success" : s.state === "failed" ? "danger" : "primary"}>{t(`skills:state.${s.state}`)}</Badge>
            <span className="flex-1 text-muted">{t("skills:interview.turns", { count: s.turn_count })} · {timeAgo(s.created_at, i18n.language)}</span>
            <Link className="font-medium text-primary hover:underline" to={`/p/${projectId}/skills/${skillId}/interview/${s.id}`}>{t("common:actions.edit")}</Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function KnowledgeTab() {
  const { skillId = "" } = useParams();
  const { t } = useTranslation(["skills", "common"]);
  const history = useKnowledgeHistory(skillId);
  if (history.isLoading) return <Skeleton className="h-40" />;
  const latest = history.data?.[0];
  if (!latest) return <EmptyState title={t("common:status.empty")} />;
  return <KnowledgePanel knowledge={latest} expanded />;
}
