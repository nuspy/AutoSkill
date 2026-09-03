import { useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Search } from "lucide-react";
import { useHubHome, useHubSearch } from "@/api/hooks/hub";
import { Input } from "@/components/ui/input";
import { EmptyState, PageHeader, Skeleton } from "@/components/ui/misc";
import { SkillCard } from "./SkillCard";
import { cn } from "@/lib/cn";

export default function HubHomePage() {
  const { t, i18n } = useTranslation(["skills", "common"]);
  const home = useHubHome();
  const [q, setQ] = useState("");
  const [category, setCategory] = useState<string>("");
  const [sort, setSort] = useState("published");
  const searching = q.length > 0 || category.length > 0;
  const results = useHubSearch({ q, category, sort });
  const lang = i18n.language.slice(0, 2);
  const Section = ({ title, items }: { title: string; items: typeof home.data extends undefined ? never : NonNullable<typeof home.data>["latest"] }) =>
    items.length ? (
      <section>
        <h2 className="mb-3 text-lg font-semibold">{title}</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{items.map((s) => <SkillCard key={s.id} skill={s} />)}</div>
      </section>
    ) : null;
  return (
    <>
      <PageHeader title={t("skills:hub.title")} subtitle={t("skills:hub.subtitle")} />
      <div className="mb-6 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-64"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted" /><Input className="pl-9" placeholder={t("skills:hub.searchPlaceholder")} value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <select className="h-10 rounded-lg border border-border bg-card px-3 text-sm" value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="published">{t("skills:hub.sort.published")}</option><option value="installs">{t("skills:hub.sort.installs")}</option><option value="updated">{t("skills:hub.sort.updated")}</option><option value="title">{t("skills:hub.sort.title")}</option>
        </select>
      </div>
      {home.data && home.data.categories.length > 0 && (
        <div className="mb-6 flex flex-wrap gap-2">
          <button className={cn("rounded-full border px-3 py-1 text-sm", !category ? "border-primary bg-primary/10 text-primary" : "border-border")} onClick={() => setCategory("")}>{t("skills:hub.allCategories")}</button>
          {home.data.categories.map((c) => <button key={c.id} className={cn("rounded-full border px-3 py-1 text-sm", category === c.slug ? "border-primary bg-primary/10 text-primary" : "border-border hover:bg-accent")} onClick={() => setCategory(c.slug)}>{c.name[lang] ?? c.name.en ?? c.slug} <span className="text-muted">{c.count}</span></button>)}
        </div>
      )}
      {home.isLoading && <Skeleton className="h-48" />}
      {searching ? (
        results.data ? (results.data.items.length ? <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{results.data.items.map((s) => <SkillCard key={s.id} skill={s} />)}</div> : <EmptyState title={t("skills:hub.noResults")} />) : <Skeleton className="h-48" />
      ) : home.data ? (
        <div className="space-y-10">
          <Section title={t("skills:hub.featured")} items={home.data.featured} />
          <Section title={t("skills:hub.latest")} items={home.data.latest} />
          <Section title={t("skills:hub.mostInstalled")} items={home.data.most_installed} />
          {home.data.latest.length === 0 && <EmptyState title={t("skills:hub.empty")} description={t("skills:hub.emptyHelp")} action={<Link to="/" className="text-primary hover:underline">{t("nav.projects", { ns: "common" })}</Link>} />}
        </div>
      ) : null}
    </>
  );
}
