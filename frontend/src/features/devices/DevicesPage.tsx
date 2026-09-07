import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { MonitorSmartphone, Trash2 } from "lucide-react";
import { useCompanion, useDevices, useRemoveDevice } from "@/api/hooks/me";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge, EmptyState, PageHeader, Skeleton } from "@/components/ui/misc";
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
        <Card>
          <CardHeader title={t("me:devices.connect")} description={t("me:devices.howto")} />
          <CardBody className="space-y-3">
            {companion.isLoading && <Skeleton className="h-20" />}
            {companion.isSuccess && !install && <p className="text-sm text-muted">{t("me:devices.noWheel")}</p>}
            {install && (
              <>
                <pre className="overflow-x-auto rounded-lg bg-accent p-3 font-mono text-xs">{`${install}\nautoskill login ${serverUrl}\nautoskill skill assistant`}</pre>
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
