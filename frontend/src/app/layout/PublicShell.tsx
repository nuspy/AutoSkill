import { Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";

export function PublicShell() {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-full items-center justify-center bg-bg px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-6 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-primary text-xl font-bold text-primary-fg">A</div>
          <h1 className="text-2xl font-semibold">{t("app.name")}</h1>
          <p className="mt-1 text-sm text-muted">{t("app.tagline")}</p>
        </div>
        <Outlet />
      </div>
    </div>
  );
}
