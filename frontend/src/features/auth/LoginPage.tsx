import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useLogin } from "@/api/hooks/auth";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { ErrorState } from "@/components/ui/misc";
import { errorMessage } from "@/lib/errors";

export default function LoginPage() {
  const { t } = useTranslation(["auth", "common"]);
  const login = useLogin();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    login.mutate({ email, password }, { onSuccess: () => navigate((location.state as { from?: { pathname: string } })?.from?.pathname || "/", { replace: true }) });
  };

  return (
    <Card>
      <CardBody className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold">{t("auth:login.title")}</h2>
          <p className="text-sm text-muted">{t("auth:login.subtitle")}</p>
        </div>
        <form className="space-y-4" onSubmit={submit}>
          <Field label={t("auth:fields.email")}>
            <Input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field label={t("auth:fields.password")}>
            <Input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
          {login.isError && <ErrorState message={errorMessage(login.error, t)} />}
          <Button type="submit" className="w-full" loading={login.isPending}>{t("auth:login.submit")}</Button>
        </form>
        <p className="text-center text-sm text-muted">
          {t("auth:login.noAccount")} <Link to="/register" className="font-medium text-primary hover:underline">{t("auth:login.register")}</Link>
        </p>
      </CardBody>
    </Card>
  );
}
