"use client";

import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  changePassword as changePasswordRequest,
  getMe,
  login as loginRequest,
  logout as logoutRequest,
  type MeResponse,
} from "@/lib/backend/auth";
import { BackendError } from "@/lib/backend/http";
import {
  AUTH_SESSION_STORAGE_KEY,
  clearAuthSession,
  getAuthSession,
  storeAuthSession,
} from "@/lib/auth/token-store";

interface AuthState {
  user: MeResponse | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  error: Error | null;
}

interface AuthContextValue extends AuthState {
  login: (loginIdentifier: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  changePassword: (oldPassword: string, newPassword: string) => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function loginDestination(): string {
  const from = new URLSearchParams(window.location.search).get("from");
  return from && /^\/(?![\\/])/.test(from) ? from : "/chat";
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    isLoading: true,
    isAuthenticated: false,
    error: null,
  });
  const requestVersionRef = useRef(0);

  const refresh = useCallback(async () => {
    const requestVersion = ++requestVersionRef.current;
    setState((current) => ({ ...current, isLoading: true, error: null }));
    try {
      const user = await getMe();
      if (requestVersion !== requestVersionRef.current) return;
      // When backend auth is disabled, /me intentionally returns a 200 system
      // identity with authenticated=false. HTTP success still grants UI access.
      setState({ user, isLoading: false, isAuthenticated: true, error: null });
    } catch (error) {
      if (requestVersion !== requestVersionRef.current) return;
      if (error instanceof BackendError && error.status === 401) clearAuthSession();
      setState({
        user: null,
        isLoading: false,
        isAuthenticated: false,
        error: error instanceof Error ? error : new Error("认证状态检查失败"),
      });
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    function syncAuthSession(event: StorageEvent) {
      if (event.key !== null && event.key !== AUTH_SESSION_STORAGE_KEY) return;

      if (!getAuthSession()) {
        requestVersionRef.current += 1;
        setState({
          user: null,
          isLoading: false,
          isAuthenticated: false,
          error: null,
        });
        return;
      }

      void refresh();
    }

    window.addEventListener("storage", syncAuthSession);
    return () => window.removeEventListener("storage", syncAuthSession);
  }, [refresh]);

  const login = useCallback(async (loginIdentifier: string, password: string) => {
    const session = await loginRequest({
      login_identifier: loginIdentifier,
      password,
    });
    storeAuthSession({
      accessToken: session.access_token,
      tokenType: session.token_type || "bearer",
      expiresAt: session.expires_at,
      userId: session.user_id,
      username: session.username,
      companyId: session.company_id,
    });
    const requestVersion = ++requestVersionRef.current;

    try {
      const user = await getMe();
      if (requestVersion !== requestVersionRef.current) return;
      setState({ user, isLoading: false, isAuthenticated: true, error: null });
    } catch (error) {
      if (requestVersion !== requestVersionRef.current) return;
      clearAuthSession();
      throw error;
    }
    if (requestVersion !== requestVersionRef.current) return;
    window.location.href = loginDestination();
  }, []);

  const logout = useCallback(async () => {
    requestVersionRef.current += 1;
    try {
      await logoutRequest();
    } catch {
      // Local logout must still complete when the backend is unavailable.
    } finally {
      requestVersionRef.current += 1;
      clearAuthSession();
      setState({ user: null, isLoading: false, isAuthenticated: false, error: null });
      window.location.href = "/login";
    }
  }, []);

  const changePassword = useCallback(async (oldPassword: string, newPassword: string) => {
    try {
      await changePasswordRequest({ old_password: oldPassword, new_password: newPassword });
    } catch (error) {
      if (error instanceof BackendError && error.status === 401) {
        requestVersionRef.current += 1;
        clearAuthSession();
        setState({ user: null, isLoading: false, isAuthenticated: false, error: null });
        window.location.href = "/login";
      }
      throw error;
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ ...state, login, logout, changePassword, refresh }),
    [state, login, logout, changePassword, refresh]
  );

  return createElement(AuthContext.Provider, { value }, children);
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}
