import { Link, NavLink, Outlet, useNavigate } from "react-router";
import { useAuth } from "../auth";

const navClass = ({ isActive }: { isActive: boolean }) =>
  `rounded px-2 py-1 text-sm ${isActive ? "bg-indigo-50 font-medium text-indigo-700" : "text-slate-600 hover:text-slate-900"}`;

export default function Layout() {
  const { status, me, signOut } = useAuth();
  const navigate = useNavigate();
  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-4xl flex-wrap items-center gap-3 px-4 py-3">
          <Link to="/" className="mr-2 font-semibold text-indigo-700">
            Literature Fetch
          </Link>
          {status === "signedIn" && (
            <nav className="flex flex-wrap gap-1">
              <NavLink to="/settings" className={navClass}>Settings</NavLink>
              <NavLink to="/digests" className={navClass}>Past digests</NavLink>
              <NavLink to="/account" className={navClass}>Account</NavLink>
              {me?.admin && <NavLink to="/admin" className={navClass}>Admin</NavLink>}
            </nav>
          )}
          <div className="ml-auto flex items-center gap-3 text-sm">
            {status === "signedIn" ? (
              <>
                <span className="hidden text-slate-500 sm:inline">{me?.email}</span>
                <button
                  className="btn py-1"
                  onClick={async () => {
                    await signOut();
                    navigate("/");
                  }}
                >
                  Sign out
                </button>
              </>
            ) : (
              status === "signedOut" && <Link to="/login" className="btn py-1">Sign in</Link>
            )}
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  );
}
