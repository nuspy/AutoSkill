import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { useResetPassword } from "@/api/hooks/auth";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { ErrorState } from "@/components/ui/misc";
import { errorMessage } from "@/lib/errors";

export default function ResetPasswordPage() {
  const { t } = useTranslation(["auth", "common"]);
  const { token = "" } = useParams();
  const navigate = useNavigate();
  const reset = useResetPassword();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (password !== confirm) { toast.error(t("auth:reset.mismatch")); return; }
    reset.mutate({ token, new_password: password }, { onSuccess: () => { toast.success(t("auth:reset.done")); navigate("/login", { replace: true }); } });
  };
  return (
    <Card>
      <CardBody className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold">{t("auth:reset.title")}</h2>
          <p className="text-sm text-muted">{t("auth:reset.subtitle")}</p>
        </div>
        <form className="space-y-4" onSubmit={submit}>
          <Field label={t("auth:fields.newPassword")}><Input type="password" autoComplete="new-password" minLength={8} required value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
          <Field label={t("auth:reset.confirm")}><Input type="password" autoComplete="new-password" minLength={8} required value={confirm} onChange={(e) => setConfirm(e.target.value)} /></Field>
          {reset.isError && <ErrorState message={errorMessage(reset.error, t)} />}
          <Button type="submit" className="w-full" loading={reset.isPending}>{t("auth:reset.submit")}</Button>
        </form>
        <p className="text-center text-sm text-muted"><Link to="/login" className="font-medium text-primary hover:underline">{t("auth:register.login")}</Link></p>
      </CardBody>
    </Card>
  );
}
