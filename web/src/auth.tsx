// Who is signed in, and their /me record, shared with every page.
import { getCurrentUser, signOut as amplifySignOut } from "aws-amplify/auth";
import { Hub } from "aws-amplify/utils";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, idToken, type Me } from "./api";

type Status = "loading" | "signedOut" | "signedIn";

type AuthState = {
  status: Status;
  me: Me | null;
  meError: string | null;
  refresh: () => Promise<void>;
  refreshMe: (newToken?: boolean) => Promise<Me | null>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [me, setMe] = useState<Me | null>(null);
  const [meError, setMeError] = useState<string | null>(null);

  // newToken: fetch a fresh ID token first (e.g. after being added to the admins group).
  const refreshMe = useCallback(async (newToken = false) => {
    try {
      if (newToken) await idToken(true);
      const m = await api<Me>("GET", "/me");
      setMe(m);
      setMeError(null);
      return m;
    } catch (e) {
      setMeError(e instanceof Error ? e.message : String(e));
      return null;
    }
  }, []);

  const check = useCallback(async () => {
    try {
      await getCurrentUser();
      setStatus("signedIn");
      await refreshMe();
    } catch {
      setStatus("signedOut");
      setMe(null);
    }
  }, [refreshMe]);

  useEffect(() => {
    check();
    // Amplify announces sign-in / sign-out / failed token refresh on its "auth" channel.
    return Hub.listen("auth", ({ payload }) => {
      if (payload.event === "signedIn") check();
      if (payload.event === "signedOut" || payload.event === "tokenRefresh_failure") {
        setStatus("signedOut");
        setMe(null);
      }
    });
  }, [check]);

  const signOut = useCallback(async () => {
    await amplifySignOut();
    setStatus("signedOut");
    setMe(null);
  }, []);

  return (
    <AuthContext.Provider value={{ status, me, meError, refresh: check, refreshMe, signOut }}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be inside <AuthProvider>");
  return ctx;
}
