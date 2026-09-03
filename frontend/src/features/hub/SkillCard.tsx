import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Download, Star } from "lucide-react";
import type { HubSkill } from "@/api/types";
import { useToggleFavorite } from "@/api/hooks/hub";
import { Card, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/misc";
import { Stars } from "@/components/ui/stars";
import { cn } from "@/lib/cn";

export function SkillCard({ skill }: { skill: HubSkill }) {
  const { t } = useTranslation(["skills"]);
  const fav = useToggleFavorite();
  return (
    <Card className="h-full transition hover:border-primary/50 hover:shadow-md">
      <CardBody className="flex h-full flex-col">
        <div className="flex items-start gap-2">
          <Link to={`/hub/s/${skill.id}`} className="flex-1 font-semibold hover:text-primary">{skill.title}</Link>
          <button aria-label={t("skills:hub.favorite")} className={cn("rounded p-1", skill.is_favorite ? "text-warning" : "text-muted hover:text-fg")} onClick={() => fav.mutate({ skillId: skill.id, on: !skill.is_favorite })}><Star className="h-4 w-4" fill={skill.is_favorite ? "currentColor" : "none"} /></button>
        </div>
        <p className="mt-1 line-clamp-3 flex-1 text-sm text-muted">{skill.summary}</p>
        <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs text-muted">
          <code className="rounded bg-accent px-1">v{skill.published_version}</code>
          {skill.category_slug && <Badge>{skill.category_slug}</Badge>}
          {skill.tags.slice(0, 3).map((tg) => <Badge key={tg} tone="neutral">#{tg}</Badge>)}
          <span className="ml-auto flex items-center gap-2">{skill.rating_count > 0 && <Stars value={skill.rating_avg} count={skill.rating_count} size="h-3 w-3" />}<span className="flex items-center gap-1"><Download className="h-3 w-3" />{skill.install_count}</span></span>
        </div>
      </CardBody>
    </Card>
  );
}
