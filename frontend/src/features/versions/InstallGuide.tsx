import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Copy, Link2, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useDownloadLinkMutations, useDownloadLinks, useInstallDoc, useTargets } from "@/api/hooks/versions";
import { Button } from "@/components/ui/button";
import { CopyRow } from "@/components/ui/copy-row";
import { Field, Input, Select } from "@/components/ui/input";
import { Markdown } from "@/components/ui/markdown";
import { Badge, ErrorState, Skeleton } from "@/components/ui/misc";
import { errorMessage } from "@/lib/errors";
import { timeAgo } from "@/lib/format";
import { cn } from "@/lib/cn";

export function InstallGuide({ versionId, trial = false }: { versionId: string; trial?: boolean }) {
  const { t } = useTranslation(["skills", "common"]);
  const targets = useTargets();
  const [target, setTarget] = useState("hermes");
  const doc = useInstallDoc(versionId, target, trial);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1">
        {targets.data?.map((tg) => (
          <button key={tg.id} className={cn("rounded-full border px-3 py-1 text-sm", target === tg.id ? "border-primary bg-primary/10 text-primary" : "border-border hover:bg-accent")} onClick={() => setTarget(tg.id)}>{tg.display_name}</button>
        ))}
        <Button size="sm" variant="ghost" className="ml-auto" disabled={!doc.data} onClick={() => { navigator.clipboard.writeText(doc.data?.markdown ?? ""); toast.success(t("common:actions.copied")); }}><Copy className="h-3.5 w-3.5" />{t("common:actions.copy")}</Button>
      </div>
      {!trial && <DownloadLinks versionId={versionId} target={target} isPublic={doc.data?.public ?? true} bundleUrl={doc.data?.bundle_url ?? null} manifestUrl={doc.data?.manifest_url ?? null} />}
      {doc.data ? <Markdown source={doc.data.markdown} /> : <Skeleton className="h-48" />}
    </div>
  );
}

function DownloadLinks({ versionId, target, isPublic, bundleUrl, manifestUrl }: { versionId: string; target: string; isPublic: boolean; bundleUrl: string | null; manifestUrl: string | null }) {
  const { t, i18n } = useTranslation(["skills", "common"]);
  const links = useDownloadLinks(versionId);
  const { create, revoke } = useDownloadLinkMutations(versionId);
  const [days, setDays] = useState("30");
  const [label, setLabel] = useState("");
  const active = links.data?.filter((l) => !l.revoked_at) ?? [];
  return (
    <div className="space-y-3 rounded-lg border border-border p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Link2 className="h-4 w-4 text-primary" />
        <p className="font-medium">{t("skills:install.links.title")}</p>
        <p className="w-full text-xs text-muted">{isPublic ? t("skills:install.links.publicHint") : t("skills:install.links.hint")}</p>
      </div>
      {bundleUrl && !isPublic && (
        <>
          <CopyRow label={t("skills:install.links.bundleUrl")} value={bundleUrl} />
          {manifestUrl && <CopyRow label={t("skills:install.links.manifestUrl")} value={manifestUrl} hint={t("skills:install.links.agentHint")} />}
        </>
      )}
      <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); create.mutate({ expires_in_days: Number(days) || undefined, label: label || undefined, target_agent: target }, { onSuccess: () => { setLabel(""); toast.success(t("skills:install.links.created")); } }); }}>
        <Field label={t("skills:install.links.expires")}>
          <Select value={days} onChange={(e) => setDays(e.target.value)}>
            <option value="7">7</option><option value="30">30</option><option value="90">90</option><option value="365">365</option>
          </Select>
        </Field>
        <Field label={t("skills:install.links.label")}><Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder={t("skills:install.links.labelPlaceholder")} /></Field>
        <Button type="submit" size="sm" loading={create.isPending}><Link2 className="h-4 w-4" />{t("skills:install.links.create")}</Button>
      </form>
      {create.isError && <ErrorState message={errorMessage(create.error, t)} />}
      {active.length > 0 && (
        <ul className="divide-y divide-border">
          {active.map((l) => (
            <li key={l.id} className="flex flex-wrap items-center gap-2 py-2">
              <Badge>{l.target_agent ?? "-"}</Badge>
              <span className="min-w-0 flex-1 truncate font-mono text-xs">{l.bundle_url}</span>
              <span className="text-xs text-muted">{l.label} · {t("skills:install.links.downloads", { n: l.download_count })}{l.expires_at ? ` · ${t("skills:install.links.expiresAt", { when: timeAgo(l.expires_at, i18n.language) })}` : ""}</span>
              <Button size="icon" variant="ghost" aria-label={t("common:actions.copy")} onClick={() => { navigator.clipboard.writeText(l.bundle_url); toast.success(t("common:actions.copied")); }}><Copy className="h-4 w-4" /></Button>
              <Button size="icon" variant="ghost" aria-label={t("skills:install.links.revoke")} onClick={() => revoke.mutate(l.id)}><Trash2 className="h-4 w-4 text-danger" /></Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
