import { lazy, Suspense } from "react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { AppShell } from "./layout/AppShell";
import { PublicShell } from "./layout/PublicShell";
import { RedirectIfAuthed, RequireAdmin, RequireAuth } from "./guards";
import { Spinner } from "@/components/ui/misc";

const LoginPage = lazy(() => import("@/features/auth/LoginPage"));
const RegisterPage = lazy(() => import("@/features/auth/RegisterPage"));
const DevicePage = lazy(() => import("@/features/auth/DevicePage"));
const ProjectsPage = lazy(() => import("@/features/projects/ProjectsPage"));
const ProjectPage = lazy(() => import("@/features/projects/ProjectPage"));
const ProjectSettingsPage = lazy(() => import("@/features/projects/ProjectSettingsPage"));
const ProfilePage = lazy(() => import("@/features/me/ProfilePage"));
const DevicesPage = lazy(() => import("@/features/devices/DevicesPage"));
const NotificationsPage = lazy(() => import("@/features/notifications/NotificationsPage"));
const AdminPage = lazy(() => import("@/features/admin/AdminPage"));
const HubPlaceholder = lazy(() => import("@/features/projects/HubPlaceholder"));
const NewSkillPage = lazy(() => import("@/features/skills/NewSkillPage"));
const SkillPage = lazy(() => import("@/features/skills/SkillPage"));

const fallback = <div className="flex justify-center py-16"><Spinner /></div>;
const page = (el: React.ReactNode) => <Suspense fallback={fallback}>{el}</Suspense>;

const router = createBrowserRouter([
  {
    element: <RedirectIfAuthed />,
    children: [
      {
        element: <PublicShell />,
        children: [
          { path: "/login", element: page(<LoginPage />) },
          { path: "/register", element: page(<RegisterPage />) },
        ],
      },
    ],
  },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppShell />,
        children: [
          { path: "/", element: page(<ProjectsPage />) },
          { path: "/device", element: page(<DevicePage />) },
          { path: "/hub", element: page(<HubPlaceholder />) },
          { path: "/p/:projectId", element: page(<ProjectPage />) },
          { path: "/p/:projectId/settings", element: page(<ProjectSettingsPage />) },
          { path: "/p/:projectId/skills/new", element: page(<NewSkillPage />) },
          { path: "/p/:projectId/skills/:skillId/*", element: page(<SkillPage />) },
          { path: "/me", element: page(<ProfilePage />) },
          { path: "/me/devices", element: page(<DevicesPage />) },
          { path: "/me/notifications", element: page(<NotificationsPage />) },
          {
            element: <RequireAdmin />,
            children: [{ path: "/admin/*", element: page(<AdminPage />) }],
          },
        ],
      },
    ],
  },
]);

export function AppRouter() {
  return <RouterProvider router={router} />;
}
