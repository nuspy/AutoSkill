import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useRegister } from "@/api/hooks/auth";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { ErrorState } from "@/components/ui/misc";
import { errorMessage } from "@/lib/errors";
import { LOCALE_NAMES, SUPPORTED_LOCALES } from "@/i18n";

export default function RegisterPage() {
  const { t, i18n } = useTranslation(["auth", "common"]);
  const register = useRegister();
  const navigate = useNavigate();
  const [form, setForm] = useState({ email: "", password: "", display_name: "", locale: i18n.language.slice(0, 2) || "en" });
  const update = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm({ ...form, [k]: e.target.value });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    register.mutate(form, {
      onSuccess: () => {
        i18n.changeLanguage(form.locale);
        navigate("/", { replace: true });
      },
    });
  };

  return (
    <Card>
      <CardBody className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold">{t("auth:register.title")}</h2>
          <p className="text-sm text-muted">{t("auth:register.subtitle")}</p>
        </div>
        <form className="space-y-4" onSubmit={submit}>
          <Field label={t("auth:fields.displayName")}>
            <Input required value={form.display_name} onChange={update("display_name")} />
          </Field>
          <Field label={t("auth:fields.email")}>
            <Input type="email" autoComplete="email" required value={form.email} onChange={update("email")} />
          </Field>
          <Field label={t("auth:fields.password")}>
            <Input type="password" autoComplete="new-password" minLength={8} required value={form.password} onChange={update("password")} />
          </Field>
          <Field label={t("auth:fields.locale")}>
            <Select value={form.locale} onChange={update("locale")}>
              {SUPPORTED_LOCALES.map((l) => <option key={l} value={l}>{LOCALE_NAMES[l]}</option>)}
            </Select>
          </Field>
          {register.isError && <ErrorState message={errorMessage(register.error, t)} />}
          <Button type="submit" className="w-full" loading={register.isPending}>{t("auth:register.submit")}</Button>
        </form>
        <p className="text-center text-sm text-muted">
          {t("auth:register.haveAccount")} <Link to="/login" className="font-medium text-primary hover:underline">{t("auth:register.login")}</Link>
        </p>
      </CardBody>
    </Card>
  );
}
