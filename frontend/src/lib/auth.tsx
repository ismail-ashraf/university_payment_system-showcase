"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { apiGet } from "@/lib/api";

export type AuthState = {
  is_authenticated: boolean;
  is_admin: boolean;
  student_id: string | null;
};

type AuthContextValue = {
  loading: boolean;
  auth: AuthState;
  refresh: () => Promise<AuthState>;
};

const defaultAuth: AuthState = {
  is_authenticated: false,
  is_admin: false,
  student_id: null,
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [auth, setAuth] = useState<AuthState>(defaultAuth);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    try {
      const data = await apiGet<AuthState>("/api/auth/whoami/");
      const next = {
        is_authenticated: Boolean(data.is_authenticated),
        is_admin: Boolean(data.is_admin),
        student_id: data.student_id ?? null,
      };
      setAuth(next);
      return next;
    } catch {
      setAuth(defaultAuth);
      return defaultAuth;
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  const value = useMemo(() => ({ loading, auth, refresh }), [loading, auth]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}

export function useAuthGuard(options: { requireAdmin?: boolean; studentId?: string }) {
  const { loading, auth } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [accessDenied, setAccessDenied] = useState(false);

  useEffect(() => {
    if (loading) return;

    if (!auth.is_authenticated) {
      const next = encodeURIComponent(pathname || "/");
      router.replace(`/login?next=${next}`);
      return;
    }

    if (options.requireAdmin && !auth.is_admin) {
      setAccessDenied(true);
      return;
    }

    if (options.studentId && !auth.is_admin) {
      if (!auth.student_id || auth.student_id !== options.studentId) {
        setAccessDenied(true);
        return;
      }
    }

    setAccessDenied(false);
  }, [loading, auth, options.requireAdmin, options.studentId, pathname, router]);

  return { loading, accessDenied };
}

type VerifiedStatus = {
  verified: boolean;
  student_id: string | null;
  expires_at: string | null;
};

export function useStudentGuard(studentId: string) {
  const { loading: authLoading, auth } = useAuth();
  const router = useRouter();
  const [checking, setChecking] = useState(true);
  const [verifiedStatus, setVerifiedStatus] = useState<VerifiedStatus>({
    verified: false,
    student_id: null,
    expires_at: null,
  });
  const [accessDenied, setAccessDenied] = useState(false);

  useEffect(() => {
    if (authLoading) return;
    if (auth.is_authenticated) {
      setChecking(false);
      return;
    }
    let active = true;
    async function load() {
      try {
        const data = await apiGet<VerifiedStatus>("/api/students/verify/status/");
        if (!active) return;
        setVerifiedStatus(data);
      } catch {
        if (!active) return;
        setVerifiedStatus({ verified: false, student_id: null, expires_at: null });
      } finally {
        if (active) setChecking(false);
      }
    }
    load();
    return () => {
      active = false;
    };
  }, [authLoading, auth.is_authenticated]);

  useEffect(() => {
    if (authLoading || checking) return;

    if (auth.is_authenticated) {
      if (auth.is_admin) {
        setAccessDenied(false);
        return;
      }
      if (auth.student_id && auth.student_id === studentId) {
        setAccessDenied(false);
        return;
      }
      setAccessDenied(true);
      return;
    }

    if (verifiedStatus.verified) {
      if (verifiedStatus.student_id === studentId) {
        setAccessDenied(false);
        return;
      }
      setAccessDenied(true);
      return;
    }

    router.replace("/");
  }, [authLoading, checking, auth, verifiedStatus, router, studentId]);

  return { loading: authLoading || checking, accessDenied };
}

export function isSafeNextPath(value: string | null) {
  if (!value) return false;
  if (!value.startsWith("/")) return false;
  if (value.startsWith("//")) return false;
  if (value.includes("://")) return false;
  return true;
}
