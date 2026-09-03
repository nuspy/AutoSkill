import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { useChangePassword, useUpdateProfile } from "@/api/hooks/auth";
import { useSession } from "@/stores/session";
import { useUi } from "@/stores/ui";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { ErrorState, PageHeader } from "@/components/ui/misc";
import { errorMessage } from "@/lib/errors";
import { LOCALE_NAMES, SUPPORTED_LOCALES } from "@/i18n";

export default function ProfilePage() {
  const { t, i18n } = useTranslation(["me", "auth", "common"]);
  const user = useSession((s) => s.user)!;
  const { theme, setTheme } = useUi();
  const update = useUpdateProfile();
  const changePassword = useChangePassword();
  const [name, setName] = useState(user.display_name);
  const [locale, setLocale] = useState(user.locale);
  const [pw, setPw] = useState({ current_password: "", new_password: "" });

  const save = (e: FormEvent) => {
    e.preventDefault();
    update.mutate({ display_name: name, locale }, { onSuccess: () => { i18n.changeLanguage(locale); toast.success(t("me:profile.saved")); } });
  };
  const savePw = (e: FormEvent) => {
    e.preventDefault();
    changePassword.mutate(pw, { onSuccess: () => { toast.success(t("me:profile.passwordChanged")); setPw({ current_password: "", new_password: "" }); } });
  };

  return (
    <>
      <PageHeader title={t("me:profile.title")} subtitle={user.email} />
      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader title={t("me:profile.title")} />
          <CardBody>
            <form className="space-y-4" onSubmit={save}>
              <Field label={t("auth:fields.displayName")}><Input value={name} onChange={(e) => setName(e.target.value)} required /></Field>
              <Field label={t("auth:fields.locale")}>
                <Select value={locale} onChange={(e) => setLocale(e.target.value)}>{SUPPORTED_LOCALES.map((l) => <option key={l} value={l}>{LOCALE_NAMES[l]}</option>)}</Select>
              </Field>
              <Field label="Theme">
                <Select value={theme} onChange={(e) => setTheme(e.target.value as "light" | "dark" | "system")}>
                  {(["light", "dark", "system"] as const).map((v) => <option key={v} value={v}>{t(`common:theme.${v}`)}</option>)}
                </Select>
              </Field>
              {update.isError && <ErrorState message={errorMessage(update.error, t)} />}
              <Button type="submit" loading={update.isPending}>{t("common:actions.save")}</Button>
            </form>
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t("me:profile.password")} />
          <CardBody>
            <form className="space-y-4" onSubmit={savePw}>
              <Field label={t("auth:fields.currentPassword")}><Input type="password" autoComplete="current-password" required value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} /></Field>
              <Field label={t("auth:fields.newPassword")}><Input type="password" autoComplete="new-password" minLength={8} required value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} /></Field>
              {changePassword.isError && <ErrorState message={errorMessage(changePassword.error, t)} />}
              <Button type="submit" loading={changePassword.isPending}>{t("common:actions.save")}</Button>
            </form>
          </CardBody>
        </Card>
      </div>
    </>
  );
}
