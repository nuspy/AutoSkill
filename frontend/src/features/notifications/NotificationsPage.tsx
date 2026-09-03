import { useTranslation } from "react-i18next";
import { useMarkRead, useNotifications } from "@/api/hooks/me";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, PageHeader, Skeleton } from "@/components/ui/misc";
import { timeAgo } from "@/lib/format";
import { cn } from "@/lib/cn";

export default function NotificationsPage() {
  const { t, i18n } = useTranslation(["me", "common"]);
  const notifications = useNotifications(false);
  const markRead = useMarkRead();
  return (
    <>
      <PageHeader title={t("me:notifications.title")} actions={<Button variant="outline" onClick={() => markRead.mutate("all")} disabled={!notifications.data?.unread}>{t("common:actions.markAllRead")}</Button>} />
      {notifications.isLoading && <Skeleton className="h-32" />}
      {notifications.data && notifications.data.items.length === 0 && <EmptyState title={t("me:notifications.empty")} />}
      {notifications.data && notifications.data.items.length > 0 && (
        <Card>
          <ul className="divide-y divide-border">
            {notifications.data.items.map((n) => (
              <li key={n.id} className={cn("flex items-start gap-3 px-5 py-3", !n.read_at && "bg-primary/5")}>
                <span className={cn("mt-2 h-2 w-2 shrink-0 rounded-full", n.read_at ? "bg-border" : "bg-primary")} />
                <div className="flex-1">
                  <p className="text-sm font-medium">{n.title}</p>
                  {n.body && <p className="text-sm text-muted">{n.body}</p>}
                  <p className="mt-1 text-xs text-muted">{timeAgo(n.created_at, i18n.language)}</p>
                </div>
                {!n.read_at && <Button size="sm" variant="ghost" onClick={() => markRead.mutate(n.id)}>✓</Button>}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}
