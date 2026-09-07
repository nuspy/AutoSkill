import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Download, MonitorSmartphone, Trash2 } from "lucide-react";
import { useCompanion, useDevices, useRemoveDevice } from "@/api/hooks/me";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { CopyRow } from "@/components/ui/copy-row";
import { Badge, EmptyState, ErrorState, PageHeader, Skeleton } from "@/components/ui/misc";
import { useLocalAgent, useMachineState } from "@/api/hooks/localAgent";
import { timeAgo } from "@/lib/format";

export default function DevicesPage() {
  const { t, i18n } = useTranslation(["me", "common"]);
  const devices = useDevices();
  const remove = useRemoveDevice();
  const companion = useCompanion();
  const serverUrl = window.location.origin;
  // The command names this server's own wheel by version: `autoskill-local` is not on PyPI, and a
  // URL without the .whl in it is not something pip will install.
  const install = companion.data?.wheel ? companion.data.install_command : null;
  return (
    <>
      <PageHeader title={t("me:devices.title")} subtitle={t("me:devices.subtitle")} actions={<Link to="/device" className="inline-flex h-10 items-center rounded-lg bg-primary px-4 text-sm font-medium text-primary-fg">{t("me:devices.connect")}</Link>} />
      <div className="space-y-6">
        <ThisMachine />
        <BrowserHelper />
        <Card>
          <CardHeader title={t("me:devices.connect")} description={t("me:devices.howto")} />
          <CardBody className="space-y-3">
            {companion.isLoading && <Skeleton className="h-20" />}
            {companion.isSuccess && !install && <p className="text-sm text-muted">{t("me:devices.noWheel")}</p>}
            {install && (
              <>
                {/* The action covers the third line only. The first two install and connect the CLI
                    that the helper itself runs on, so it cannot bootstrap itself — and that is why
                    the whole block stays visible even when the button is offered. */}
                <CopyRow
                  label={t("me:devices.setupCommands")}
                  value={`${install}\nautoskill login ${serverUrl}\nautoskill skill assistant`}
                  action={{ op: "assistant" }}
                />
                <p className="text-xs text-muted">{t("me:devices.assistantSkill")}</p>
                <p className="text-xs text-muted">
                  {t("me:devices.notOnPypi")}
                  {companion.data?.version && ` · ${companion.data.package} ${companion.data.version}`}
                </p>
              </>
            )}
          </CardBody>
        </Card>
        {devices.isLoading && <Skeleton className="h-24" />}
        {devices.data && devices.data.length === 0 && <EmptyState title={t("me:devices.empty")} />}
        {devices.data && devices.data.length > 0 && (
          <Card>
            <ul className="divide-y divide-border">
              {devices.data.map((d) => (
                <li key={d.id} className="flex items-center gap-4 px-5 py-3">
                  <MonitorSmartphone className="h-5 w-5 text-muted" />
                  <div className="flex-1">
                    <p className="text-sm font-medium">{d.name} <span className="text-muted">· {d.os ?? "?"}</span></p>
                    <p className="text-xs text-muted">{t("me:devices.lastSeen")}: {timeAgo(d.last_seen_at, i18n.language)} {d.cli_version && `· CLI ${d.cli_version}`}</p>
                  </div>
                  <div className="flex gap-1">{d.agent_targets.map((a) => <Badge key={a} tone="primary">{a}</Badge>)}</div>
                  <Button variant="ghost" size="icon" aria-label={t("me:devices.remove")} onClick={() => remove.mutate(d.id)}><Trash2 className="h-4 w-4 text-danger" /></Button>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
    </>
  );
}


/** What the local helper sees on this machine — shown only when there is a helper to ask.
 *
 * The server knows what a device *reported* the last time the CLI ran; this is what is on the disk
 * right now. The two differing is not a detail: a trial installed for an agent the server believes is
 * absent looked, for a whole afternoon, like a trial that had never been installed at all.
 */
function ThisMachine() {
  const { t } = useTranslation(["me", "common"]);
  const { available, version } = useLocalAgent();
  const state = useMachineState();
  if (!available) return null;
  return (
    <Card>
      <CardHeader title={t("me:devices.thisMachine")} description={t("me:devices.thisMachineHelp", { version })} />
      <CardBody>
        {state.isLoading && <Skeleton className="h-20" />}
        {state.isError && <ErrorState message={(state.error as Error).message} />}
        {state.data && (
          <ul className="divide-y divide-border text-sm">
            {state.data.agents.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-2 py-2">
                <Badge tone={a.detected ? "success" : "neutral"}>{a.detected ? "✓" : "·"}</Badge>
                <span className="font-medium">{a.display_name}</span>
                <code className="rounded bg-accent px-1.5 py-0.5 text-xs" title={a.base}>{a.base_source}</code>
                {a.companion && (
                  <Badge tone={a.companion === "registered" ? "success" : "warning"}>{a.companion}</Badge>
                )}
                <span className="ml-auto truncate text-xs text-muted" title={a.skill_dir}>{a.skill_dir}</span>
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}


/** The one manual step, offered rather than described.
 *
 * Shown only while there is no helper on this machine: once the extension answers, `ThisMachine`
 * above says so and this would be an invitation to do something already done.
 */
function BrowserHelper() {
  const { t } = useTranslation(["me", "common"]);
  const { available } = useLocalAgent();
  if (available) return null;
  const base = window.location.origin;
  const windows = navigator.userAgent.includes("Windows");
  return (
    <Card>
      <CardHeader title={t("me:devices.helper")} description={t("me:devices.helperHelp")} />
      <CardBody className="space-y-3">
        <div className="flex flex-wrap gap-2">
          <a
            className="inline-flex h-10 items-center rounded-lg bg-primary px-4 text-sm font-medium text-primary-fg"
            href={`${base}/dl/installer/${windows ? "windows" : "unix"}`}
          >
            <Download className="mr-2 h-4 w-4" aria-hidden />
            {t(windows ? "me:devices.helperWindows" : "me:devices.helperUnix")}
          </a>
          <a
            className="inline-flex h-10 items-center rounded-lg border border-border px-4 text-sm"
            href={`${base}/dl/installer/${windows ? "unix" : "windows"}`}
          >
            {t(windows ? "me:devices.helperUnix" : "me:devices.helperWindows")}
          </a>
        </div>
        {/* Said before the download, not discovered after it: the script cannot do this last part,
            and a person who expected it to would reasonably think it had failed. */}
        <p className="text-xs text-muted">{t("me:devices.helperLastStep")}</p>
      </CardBody>
    </Card>
  );
}
