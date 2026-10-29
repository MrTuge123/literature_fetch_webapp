// Route guards. They only hide pages: the API itself checks the token (and the admins group).
import { Navigate, Outlet, useLocation } from "react-router";
import { useAuth } from "../auth";
import { Loading } from "./ui";

export function RequireAuth() {
  const { status } = useAuth();
  const location = useLocation();
  if (status === "loading") return <Loading />;
  if (status === "signedOut") return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <Outlet />;
}

export function RequireAdmin() {
  const { me } = useAuth();
  if (!me) return <Loading />;
  if (!me.admin) return <Navigate to="/settings" replace />;
  return <Outlet />;
}
