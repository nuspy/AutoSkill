import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useSession } from "@/stores/session";
import { Spinner } from "@/components/ui/misc";

export function RequireAuth() {
  const { user, ready } = useSession();
  const location = useLocation();
  if (!ready) return <div className="flex h-full items-center justify-center"><Spinner /></div>;
  if (!user) return <Navigate to="/login" state={{ from: location }} replace />;
  return <Outlet />;
}

export function RequireAdmin() {
  const user = useSession((s) => s.user);
  if (user?.role !== "admin") return <Navigate to="/" replace />;
  return <Outlet />;
}

export function RedirectIfAuthed() {
  const { user, ready } = useSession();
  if (!ready) return null;
  if (user) return <Navigate to="/" replace />;
  return <Outlet />;
}
