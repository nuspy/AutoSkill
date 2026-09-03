import { useCallback } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { Bell, FolderKanban, LogOut, Menu, Moon, MonitorSmartphone, Settings2, ShieldCheck, Store, Sun, User as UserIcon } from "lucide-react";
import { toast } from "sonner";
import { useSession } from "@/stores/session";
import { useUi } from "@/stores/ui";
import { useLogout } from "@/api/hooks/auth";
import { useNotifications } from "@/api/hooks/me";
import { useServerEvents, type ServerEvent } from "@/lib/sse";
import { cn } from "@/lib/cn";

function NavItem({ to, icon: Icon, label, end }: { to: string; icon: typeof Bell; label: string; end?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        cn("flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition", isActive ? "bg-primary/10 text-primary" : "text-muted hover:bg-accent hover:text-fg")
      }
    >
      <Icon className="h-4 w-4" aria-hidden />
      <span>{label}</span>
    </NavLink>
  );
}

export function AppShell() {
  const { t } = useTranslation();
  const user = useSession((s) => s.user);
  const { theme, setTheme, sidebarOpen, toggleSidebar } = useUi();
  const logout = useLogout();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const notifications = useNotifications(true);

  const onEvent = useCallback(
    (event: ServerEvent) => {
      if (event.type === "notification.created") {
        qc.invalidateQueries({ queryKey: ["me", "notifications"] });
        toast(String(event.data.title ?? t("nav.notifications")));
      }
      if (event.type === "job.updated") qc.invalidateQueries({ queryKey: ["admin", "jobs"] });
    },
    [qc, t],
  );
  useServerEvents("/me/events", onEvent);

  const unread = notifications.data?.unread ?? 0;
  const nextTheme = theme === "dark" ? "light" : "dark";

  return (
    <div className="flex h-full">
      <aside className={cn("flex w-64 shrink-0 flex-col border-r border-border bg-card transition-all", !sidebarOpen && "-ml-64")}>
        <div className="flex h-14 items-center gap-2 border-b border-border px-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-fg font-bold">A</div>
          <span className="font-semibold">{t("app.name")}</span>
        </div>
        <nav className="flex-1 space-y-1 p-3">
          <NavItem to="/" icon={FolderKanban} label={t("nav.projects")} end />
          <NavItem to="/hub" icon={Store} label={t("nav.hub")} />
          <NavItem to="/me/devices" icon={MonitorSmartphone} label={t("nav.devices")} />
          <NavItem to="/me/notifications" icon={Bell} label={t("nav.notifications")} />
          {user?.role === "admin" && <NavItem to="/admin" icon={ShieldCheck} label={t("nav.admin")} />}
        </nav>
        <div className="border-t border-border p-3">
          <NavItem to="/me" icon={UserIcon} label={user?.display_name ?? t("nav.profile")} />
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-between border-b border-border bg-card px-4">
          <button className="rounded-md p-2 text-muted hover:bg-accent" onClick={toggleSidebar} aria-label="menu">
            <Menu className="h-5 w-5" />
          </button>
          <div className="flex items-center gap-1">
            <button className="relative rounded-md p-2 text-muted hover:bg-accent" onClick={() => navigate("/me/notifications")} aria-label={t("nav.notifications")}>
              <Bell className="h-5 w-5" />
              {unread > 0 && <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[10px] font-bold text-white">{unread}</span>}
            </button>
            <button className="rounded-md p-2 text-muted hover:bg-accent" onClick={() => setTheme(nextTheme)} aria-label={t(`theme.${nextTheme}`)}>
              {theme === "dark" ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
            </button>
            <button className="rounded-md p-2 text-muted hover:bg-accent" onClick={() => navigate("/me")} aria-label={t("nav.profile")}>
              <Settings2 className="h-5 w-5" />
            </button>
            <button className="rounded-md p-2 text-muted hover:bg-accent" onClick={() => logout.mutate()} aria-label={t("nav.logout")}>
              <LogOut className="h-5 w-5" />
            </button>
          </div>
        </header>
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-6xl px-6 py-8">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
