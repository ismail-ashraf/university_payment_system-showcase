"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiPost } from "@/lib/api";
import { useAuth, useStudentGuard } from "@/lib/auth";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { StudentChatWidget } from "@/components/StudentChatWidget";

export default function StudentLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: { studentId: string };
}) {
  const { studentId } = params;
  const router = useRouter();
  const { refresh, auth } = useAuth();
  const { loading, accessDenied } = useStudentGuard(studentId);

  async function handleLogout() {
    if (auth.is_authenticated) {
      await apiPost("/api/auth/logout/", {});
      await refresh();
      router.replace("/login");
      return;
    }
    await apiPost("/api/students/verify/logout/", {});
    await refresh();
    router.replace("/");
  }

  if (loading) return <LoadingState />;
  if (accessDenied) return <ErrorState message="Access denied." />;

  return (
    <div className="min-h-screen">
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <div>
            <p className="text-sm text-slate-500">Student Portal</p>
            <h1 className="text-xl font-semibold">{studentId}</h1>
          </div>
          <nav className="flex gap-4 text-sm">
            <Link href={`/student/${studentId}`}>Dashboard</Link>
            <Link href={`/student/${studentId}/fees`}>Fees</Link>
            <Link href={`/student/${studentId}/payments`}>Payments</Link>
            <Link href={`/student/${studentId}/start`}>Start Payment</Link>
            <button className="text-slate-500" onClick={handleLogout}>Logout</button>
          </nav>
        </div>
      </header>
      <main className="max-w-5xl mx-auto px-6 py-6">{children}</main>
      <StudentChatWidget />
    </div>
  );
}
