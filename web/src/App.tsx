import { BrowserRouter, Navigate, Route, Routes } from "react-router";
import { AuthProvider } from "./auth";
import Layout from "./components/Layout";
import { RequireAdmin, RequireAuth } from "./components/RequireAuth";
import { missingConfig } from "./config";
import Account from "./pages/Account";
import Admin from "./pages/Admin";
import Digests from "./pages/Digests";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Settings from "./pages/Settings";

export default function App() {
  if (missingConfig.length) {
    return (
      <div className="mx-auto max-w-xl p-8">
        <h1 className="mb-2 text-xl font-semibold">Website not configured</h1>
        <p className="text-sm">
          Missing {missingConfig.join(", ")}. Run <code>python scripts/web_env.py --profile litfetch</code> from
          the repo root to write <code>web/.env.local</code>, then restart <code>npm run dev</code>.
        </p>
      </div>
    );
  }
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Landing />} />
            <Route path="/login" element={<Login />} />
            <Route element={<RequireAuth />}>
              <Route path="/settings" element={<Settings />} />
              <Route path="/digests" element={<Digests />} />
              <Route path="/account" element={<Account />} />
              <Route element={<RequireAdmin />}>
                <Route path="/admin" element={<Admin />} />
              </Route>
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
