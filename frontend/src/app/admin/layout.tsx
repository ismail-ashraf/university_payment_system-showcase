"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiPost } from "@/lib/api";
import { useAuth, useAuthGuard } from "@/lib/auth";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { refresh } = useAuth();
  const { loading, accessDenied } = useAuthGuard({ requireAdmin: true });

  async function handleLogout() {
    await apiPost("/api/auth/logout/", {});
    await refresh();
    router.replace("/login");
  }

  if (loading) return <LoadingState />;
  if (accessDenied) return <ErrorState message="Access denied." />;

  return (
    <div className="min-h-screen">
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div>
            <p className="text-sm text-slate-500">Admin Console</p>
            <h1 className="text-xl font-semibold">Payments</h1>
          </div>
          <nav className="flex gap-4 text-sm">
            <Link href="/admin">Overview</Link>
            <Link href="/admin/payments">All Payments</Link>
            <button className="text-slate-500" onClick={handleLogout}>Logout</button>
          </nav>
        </div>
      </header>
      <main className="max-w-6xl mx-auto px-6 py-6">{children}</main>
    </div>
  );
}
