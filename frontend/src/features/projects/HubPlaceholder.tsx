import { useTranslation } from "react-i18next";
import { EmptyState, PageHeader } from "@/components/ui/misc";

export default function HubPlaceholder() {
  const { t } = useTranslation();
  return (
    <>
      <PageHeader title={t("nav.hub")} />
      <EmptyState title={t("status.empty")} />
    </>
  );
}
