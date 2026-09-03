import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useForgotPassword } from "@/api/hooks/auth";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { ErrorState } from "@/components/ui/misc";
import { errorMessage } from "@/lib/errors";

export default function ForgotPasswordPage() {
  const { t } = useTranslation(["auth", "common"]);
  const forgot = useForgotPassword();
  const [email, setEmail] = useState("");
  const submit = (e: FormEvent) => { e.preventDefault(); forgot.mutate({ email }); };
  return (
    <Card>
      <CardBody className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold">{t("auth:forgot.title")}</h2>
          <p className="text-sm text-muted">{t("auth:forgot.subtitle")}</p>
        </div>
        {forgot.isSuccess ? (
          <p className="rounded-lg bg-success/10 px-3 py-2 text-sm">{t("auth:forgot.sent")}</p>
        ) : (
          <form className="space-y-4" onSubmit={submit}>
            <Field label={t("auth:fields.email")}><Input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
            {forgot.isError && <ErrorState message={errorMessage(forgot.error, t)} />}
            <Button type="submit" className="w-full" loading={forgot.isPending}>{t("auth:forgot.submit")}</Button>
          </form>
        )}
        <p className="text-center text-sm text-muted"><Link to="/login" className="font-medium text-primary hover:underline">{t("auth:register.login")}</Link></p>
      </CardBody>
    </Card>
  );
}
