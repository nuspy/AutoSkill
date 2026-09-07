import { type ReactNode, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Check, X } from "lucide-react";
import { useLlmSwitch } from "@/api/hooks/llmswitch";
import { useCompanion, useDevices } from "@/api/hooks/me";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { useSession } from "@/stores/session";

const DISMISSED_KEY = "autoskill.gettingStarted.dismissed";

function readDismissed(): boolean {
  // Private windows and locked-down browsers throw on the accessor itself.
  try {
    return window.localStorage.getItem(DISMISSED_KEY) === "1";
  } catch {
    return false;
  }
}

/** One numbered step. `done` is derived from what the account actually has, never from a click. */
function Step({ index, done, title, children }: { index: number; done: boolean; title: string; children?: ReactNode }) {
  const { t } = useTranslation("projects");
  return (
    <li className="flex gap-3">
      <span
        aria-hidden
        className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
          done ? "bg-success/15 text-success" : "bg-accent text-muted"
        }`}
      >
        {done ? <Check className="h-4 w-4" /> : index}
      </span>
      <div className="min-w-0 flex-1 space-y-2 pb-1">
        <p className="text-sm font-medium">
          {title}
          {done && <span className="sr-only"> — {t("gettingStarted.done")}</span>}
        </p>
        {children && <div className="space-y-2 text-sm text-muted">{children}</div>}
      </div>
    </li>
  );
}

function Command({ children }: { children: string }) {
  return <pre className="overflow-x-auto rounded-lg bg-accent p-3 font-mono text-xs text-fg">{children}</pre>;
}

/** Admin-only, and a component of its own so the hook behind it never runs for a member. */
function ProviderStep() {
  const { t } = useTranslation("projects");
  const state = useLlmSwitch();
  const configured = (state.data?.providers.length ?? 0) > 0;
  return (
    <Step index={1} done={configured} title={t("gettingStarted.provider.title")}>
      <p>{t("gettingStarted.provider.body")}</p>
      {!configured && (
        <Link to="/admin/providers" className="inline-flex h-10 items-center text-sm font-medium text-primary">
          {t("gettingStarted.provider.action")}
        </Link>
      )}
    </Step>
  );
}

export function GettingStarted({ hasProjects, onCreateProject }: { hasProjects: boolean; onCreateProject: () => void }) {
  const { t } = useTranslation(["projects", "common"]);
  const role = useSession((s) => s.user?.role);
  const devices = useDevices();
  const companion = useCompanion();
  const [dismissed, setDismissed] = useState(readDismissed);

  const serverUrl = window.location.origin;
  const connected = (devices.data?.length ?? 0) > 0;
  const isAdmin = role === "admin";
  const offset = isAdmin ? 1 : 0;

  const dismiss = () => {
    try {
      window.localStorage.setItem(DISMISSED_KEY, "1");
    } catch {
      /* nothing to persist to; the panel still closes for this visit */
    }
    setDismissed(true);
  };

  // Nothing left to say once the account is set up, so it retires on its own.
  if (dismissed || (hasProjects && connected)) return null;

  return (
    <Card className="mb-6">
      <CardHeader title={t("projects:gettingStarted.title")} description={t("projects:gettingStarted.subtitle")} />
      <CardBody>
        <ol className="space-y-5">
          {isAdmin && <ProviderStep />}

          <Step index={offset + 1} done={hasProjects} title={t("projects:gettingStarted.project.title")}>
            <p>{t("projects:gettingStarted.project.body")}</p>
            {!hasProjects && (
              <Button variant="outline" onClick={onCreateProject}>
                {t("projects:new")}
              </Button>
            )}
          </Step>

          <Step index={offset + 2} done={connected} title={t("projects:gettingStarted.cli.title")}>
            <p>{t("projects:gettingStarted.cli.body")}</p>
            {!connected && companion.data?.wheel && <Command>{companion.data.install_command}</Command>}
          </Step>

          <Step index={offset + 3} done={connected} title={t("projects:gettingStarted.device.title")}>
            <p>{t("projects:gettingStarted.device.body")}</p>
            {!connected && (
              <>
                <Command>{`autoskill login ${serverUrl}`}</Command>
                <Command>autoskill skill assistant</Command>
                <Link to="/device" className="inline-flex h-10 items-center text-sm font-medium text-primary">
                  {t("projects:gettingStarted.device.action")}
                </Link>
              </>
            )}
          </Step>

          <Step index={offset + 4} done={false} title={t("projects:gettingStarted.skill.title")}>
            <p>{t("projects:gettingStarted.skill.body")}</p>
          </Step>
        </ol>

        <div className="mt-6 border-t border-border pt-4">
          <Button variant="ghost" onClick={dismiss}>
            <X className="h-4 w-4" />
            {t("projects:gettingStarted.dismiss")}
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}
