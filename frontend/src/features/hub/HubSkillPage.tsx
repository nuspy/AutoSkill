import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Copy, Download, GitFork, Star } from "lucide-react";
import { toast } from "sonner";
import { useFork, useHubSkill, useInstallationMutations, useRate, useToggleFavorite } from "@/api/hooks/hub";
import { useProjects } from "@/api/hooks/projects";
import { downloadZip } from "@/api/hooks/versions";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import { Markdown } from "@/components/ui/markdown";
import { Badge, ErrorState, PageHeader, Skeleton } from "@/components/ui/misc";
import { Stars } from "@/components/ui/stars";
import { InstallGuide } from "@/features/versions/InstallGuide";
import { TrialLauncher } from "@/features/trials/TrialLauncher";
import { useSession } from "@/stores/session";
import { errorMessage } from "@/lib/errors";
import { cn } from "@/lib/cn";

export default function HubSkillPage() {
  const { skillId = "" } = useParams();
  const { t } = useTranslation(["skills", "common"]);
  const user = useSession((s) => s.user);
  const navigate = useNavigate();
  const detail = useHubSkill(skillId);
  const fav = useToggleFavorite();
  const fork = useFork();
  const { register } = useInstallationMutations();
  const projects = useProjects();
  const [tab, setTab] = useState<"overview" | "install" | "versions">("overview");
  const [target, setTarget] = useState("hermes");
  const [forkOpen, setForkOpen] = useState(false);
  const [forkProject, setForkProject] = useState("");
  const [forkTitle, setForkTitle] = useState("");
  const [comment, setComment] = useState("");
  const { rate, unrate } = useRate(skillId);
  if (detail.isLoading || !detail.data) return <Skeleton className="h-64" />;
  const d = detail.data;
  const s = d.skill;
  const vid = s.published_version_id!;
  const cli = `autoskill install --version-id ${vid} --target ${target}`;
  const editable = projects.data?.filter((p) => p.my_role === "owner" || p.my_role === "editor") ?? [];
  return (
    <>
      <PageHeader title={s.title} subtitle={s.summary ?? undefined} actions={
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => fav.mutate({ skillId: s.id, on: !s.is_favorite })}><Star className={cn("h-4 w-4", s.is_favorite && "fill-current text-warning")} />{s.is_favorite ? t("skills:hub.unfavorite") : t("skills:hub.favorite")}</Button>
          {user && <TrialLauncher versionId={vid} projectId={s.project_id} skillId={s.id} purpose="hub_evaluate" label={t("skills:hub.tryFirst")} />}
          {user && <Button variant="outline" onClick={() => setForkOpen(true)}><GitFork className="h-4 w-4" />{t("skills:hub.fork")}</Button>}
        </div>
      } />
      <div className="mb-4 flex flex-wrap items-center gap-2 text-sm text-muted">
        <code className="rounded bg-accent px-1.5 py-0.5">{s.project_slug}/{s.name}</code><Badge tone="success">v{s.published_version}</Badge>
        {s.category_slug && <Badge>{s.category_slug}</Badge>}{s.tags.map((tg) => <Badge key={tg}>#{tg}</Badge>)}
        <span className="flex items-center gap-1"><Download className="h-3.5 w-3.5" />{s.install_count} {t("skills:hub.installs")}</span>
        <Stars value={s.rating_avg} count={s.rating_count} />
        {d.my_installation && <Badge tone={d.my_installation.update_available ? "warning" : "primary"}>{d.my_installation.update_available ? t("skills:hub.updateAvailable") : t("skills:hub.installedByYou", { version: d.my_installation.installed_version })}</Badge>}
      </div>
      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <Card>
          <div className="flex gap-1 border-b border-border px-5">
            {(["overview", "install", "versions"] as const).map((k) => <button key={k} className={cn("border-b-2 px-3 py-2 text-sm font-medium", tab === k ? "border-primary text-primary" : "border-transparent text-muted")} onClick={() => setTab(k)}>{t(`skills:hub.tabs.${k}`)}</button>)}
          </div>
          <CardBody>
            {tab === "overview" && <Markdown source={d.readme} />}
            {tab === "install" && <InstallGuide versionId={vid} />}
            {tab === "versions" && (
              <ul className="divide-y divide-border text-sm">{d.versions.map((v) => <li key={v.id} className="flex items-center gap-2 py-2"><code>v{v.version}</code><Badge tone={v.state === "published" ? "success" : "neutral"}>{t(`skills:versions.state.${v.state}`)}</Badge><span className="text-muted">{v.changelog}</span></li>)}</ul>
            )}
          </CardBody>
        </Card>
        <div className="space-y-4">
          <Card>
            <CardHeader title={t("skills:hub.installTitle")} description={t("skills:hub.installHelp")} />
            <CardBody className="space-y-3 text-sm">
              <Field label={t("skills:trials.target")}><Select value={target} onChange={(e) => setTarget(e.target.value)}>{d.install_targets.map((tg) => <option key={tg.id} value={tg.id}>{tg.display_name}</option>)}</Select></Field>
              <div className="flex items-start gap-2"><pre className="flex-1 overflow-x-auto rounded-lg bg-accent p-2 font-mono text-xs">{cli}</pre><Button size="icon" variant="outline" aria-label={t("common:actions.copy")} onClick={() => { navigator.clipboard.writeText(cli); toast.success(t("common:actions.copied")); }}><Copy className="h-4 w-4" /></Button></div>
              <Button className="w-full" variant="outline" onClick={() => downloadZip(vid, `${s.name}-${s.published_version}.zip`, [target]).then(() => register.mutate({ skill_version_id: vid, target_agent: target, channel: "zip", state: "downloaded" })).catch(() => toast.error(t("common:errors.generic")))}><Download className="h-4 w-4" />{t("skills:versions.download")}</Button>
              {d.git_url && <p className="break-all text-xs text-muted">git: <code>{d.git_url}</code></p>}
              {d.dependencies.length > 0 && <p className="text-xs text-muted">{t("skills:versions.dependsOn")}: {d.dependencies.map((x) => x.component_slug).join(", ")}</p>}
            </CardBody>
          </Card>
          {user && (
            <Card>
              <CardHeader title={t("skills:hub.rating.title")} description={d.my_rating ? t("skills:hub.rating.yours", { stars: d.my_rating.stars }) : t("skills:hub.rating.help")} />
              <CardBody className="space-y-2 text-sm">
                <Stars value={d.my_rating?.stars ?? 0} onChange={(stars) => rate.mutate({ stars, comment: comment || d.my_rating?.comment || undefined }, { onSuccess: () => toast.success(t("skills:hub.rating.saved")) })} size="h-6 w-6" />
                <Input placeholder={t("skills:hub.rating.comment")} value={comment} onChange={(e) => setComment(e.target.value)} />
                {d.my_rating && <Button size="sm" variant="ghost" onClick={() => unrate.mutate()}>{t("skills:hub.rating.remove")}</Button>}
                {d.ratings.length > 0 && (
                  <ul className="divide-y divide-border">
                    {d.ratings.map((r) => <li key={r.id} className="py-2"><Stars value={r.stars} size="h-3 w-3" /> <span className="text-xs text-muted">{r.user_name}</span>{r.comment && <p className="text-muted">{r.comment}</p>}</li>)}
                  </ul>
                )}
              </CardBody>
            </Card>
          )}
          {d.memory_public.length > 0 && (
            <Card>
              <CardHeader title={t("skills:hub.why")} />
              <ul className="divide-y divide-border text-sm">{d.memory_public.map((m, i) => <li key={i} className="px-5 py-2"><p className="font-medium">{m.title}</p><p className="text-muted">{m.body}</p></li>)}</ul>
            </Card>
          )}
        </div>
      </div>
      <Dialog open={forkOpen} onClose={() => setForkOpen(false)} title={t("skills:hub.fork")} footer={<><Button variant="outline" onClick={() => setForkOpen(false)}>{t("common:actions.cancel")}</Button><Button disabled={!forkProject} loading={fork.isPending} onClick={() => fork.mutate({ skillId: s.id, target_project_id: forkProject, title: forkTitle || undefined }, { onSuccess: (sk) => { toast.success(t("skills:hub.forked")); navigate(`/p/${sk.project_id}/skills/${sk.id}`); }, onError: (e) => toast.error(errorMessage(e, t)) })}>{t("common:actions.create")}</Button></>}>
        <p className="mb-3 text-sm text-muted">{t("skills:hub.forkHelp")}</p>
        <Field label={t("skills:hub.forkProject")}><Select value={forkProject} onChange={(e) => setForkProject(e.target.value)}><option value="">—</option>{editable.filter((p) => p.id !== s.project_id).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select></Field>
        <Field label={t("skills:start.skillTitle")}><Input value={forkTitle} onChange={(e) => setForkTitle(e.target.value)} placeholder={s.title} /></Field>
        {editable.filter((p) => p.id !== s.project_id).length === 0 && <ErrorState message={t("skills:hub.forkNoProject")} />}
        <p className="mt-2 text-xs text-muted"><Link className="text-primary" to="/">{t("nav.projects", { ns: "common" })}</Link></p>
      </Dialog>
    </>
  );
}
