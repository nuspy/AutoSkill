import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useHubList } from "@/api/hooks/hub";
import { EmptyState, PageHeader, Skeleton } from "@/components/ui/misc";
import { SkillCard } from "./SkillCard";

export default function HubListPage() {
  const { slug = "" } = useParams();
  const { t, i18n } = useTranslation(["skills", "common"]);
  const list = useHubList(slug);
  const lang = i18n.language.slice(0, 2);
  if (list.isLoading || !list.data) return <Skeleton className="h-48" />;
  const l = list.data.list;
  return (
    <>
      <PageHeader title={l.name[lang] ?? l.name.en ?? l.slug} subtitle={l.description ?? undefined} actions={<Link to="/hub" className="text-sm text-primary hover:underline">{t("skills:hub.title")}</Link>} />
      {list.data.items.length ? <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{list.data.items.map((s) => <SkillCard key={s.id} skill={s} />)}</div> : <EmptyState title={t("skills:hub.empty")} />}
    </>
  );
}
