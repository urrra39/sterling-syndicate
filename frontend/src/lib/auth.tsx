import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import * as api from "./api";
import type { UserPublic } from "./api";

type AuthContextValue = {
  /** @deprecated Token is now stored in an HttpOnly cookie. This field is
   *  kept for backward compatibility with pages that pass it to API helpers.
   *  Guard checks should use `user` instead. */
  token: string | null;
  user: UserPublic | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (
    name: string,
    email: string,
    password: string,
    skills?: string[],
  ) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  // The real JWT lives in an HttpOnly cookie sent automatically by the
  // browser.  We keep a `token` string in React state purely so existing
  // page components that destructure `{ token }` from useAuth() still
  // compile and can pass it to API helpers (which now rely on the cookie,
  // ignoring an empty Bearer header).
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<UserPublic | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function hydrate() {
      try {
        // Cookie is sent automatically via credentials:"include"
        const me = await api.fetchMe("");
        if (!cancelled) {
          setUser(me);
          setToken("cookie");  // non-null sentinel so guard checks pass
        }
      } catch {
        if (!cancelled) {
          setUser(null);
          setToken(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void hydrate();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const res = await api.login({ email, password });
    // The HttpOnly cookie is set by the server response.
    setToken(res.access_token);
    setUser(res.user);
  }, []);

  const signup = useCallback(
    async (
      name: string,
      email: string,
      password: string,
      skills: string[] = [],
    ) => {
      const res = await api.signup({ name, email, password, skills });
      setToken(res.access_token);
      setUser(res.user);
    },
    [],
  );

  const logout = useCallback(async () => {
    try {
      await api.logoutApi();
    } catch {
      // Best-effort; clear local state regardless
    }
    setToken(null);
    setUser(null);
  }, []);

  // A 401 on any endpoint (expired token mid-session) dispatches this event
  // from api.request(); tear down the session so ProtectedRoute redirects.
  useEffect(() => {
    const onUnauthorized = () => {
      setToken(null);
      setUser(null);
    };
    window.addEventListener("sterling:unauthorized", onUnauthorized);
    return () => window.removeEventListener("sterling:unauthorized", onUnauthorized);
  }, []);

  const value = useMemo(
    () => ({ token, user, loading, login, signup, logout }),
    [token, user, loading, login, signup, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}
