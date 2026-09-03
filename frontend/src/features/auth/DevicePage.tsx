import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useDeviceConfirm, useDevicePending } from "@/api/hooks/me";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { Badge, ErrorState } from "@/components/ui/misc";
import { errorMessage } from "@/lib/errors";

export default function DevicePage() {
  const { t } = useTranslation(["auth", "common"]);
  const [params] = useSearchParams();
  const [code, setCode] = useState(params.get("code") ?? "");
  const [lookup, setLookup] = useState(params.get("code") ?? "");
  const pending = useDevicePending(lookup);
  const confirm = useDeviceConfirm();
  const [done, setDone] = useState<"approved" | "denied" | null>(null);

  return (
    <div className="mx-auto max-w-lg">
      <Card>
        <CardHeader title={t("auth:device.title")} description={t("auth:device.subtitle")} />
        <CardBody className="space-y-4">
          {done ? (
            <p className="text-sm">{done === "approved" ? t("auth:device.approved") : t("auth:device.denied")}</p>
          ) : (
            <>
              <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); setLookup(code.trim().toUpperCase()); }}>
                <div className="flex-1">
                  <Field label={t("auth:device.code")}>
                    <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="ABCD-EFGH" className="font-mono uppercase tracking-widest" />
                  </Field>
                </div>
                <Button type="submit" variant="outline">{t("auth:device.lookup")}</Button>
              </form>
              {pending.isError && <ErrorState message={errorMessage(pending.error, t)} />}
              {pending.data && (
                <div className="space-y-3 rounded-lg border border-border p-4">
                  <p className="text-sm">{t("auth:device.found", { name: pending.data.device_name, os: pending.data.device_os ?? "?" })}</p>
                  {pending.data.agent_targets.length > 0 && (
                    <p className="flex flex-wrap items-center gap-1 text-sm text-muted">
                      {t("auth:device.agents")}: {pending.data.agent_targets.map((a) => <Badge key={a} tone="primary">{a}</Badge>)}
                    </p>
                  )}
                  {confirm.isError && <ErrorState message={errorMessage(confirm.error, t)} />}
                  <div className="flex gap-2">
                    <Button loading={confirm.isPending} onClick={() => confirm.mutate({ user_code: lookup, approve: true }, { onSuccess: () => setDone("approved") })}>{t("common:actions.approve")}</Button>
                    <Button variant="outline" onClick={() => confirm.mutate({ user_code: lookup, approve: false }, { onSuccess: () => setDone("denied") })}>{t("common:actions.deny")}</Button>
                  </div>
                </div>
              )}
            </>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
