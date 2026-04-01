"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { apiPost } from "@/lib/api";
import { useAuth, isSafeNextPath } from "@/lib/auth";
import { Card } from "@/components/Card";
import { ErrorState } from "@/components/ErrorState";

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { refresh } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      await apiPost("/api/auth/login/", { username, password });
      const whoami = await refresh();

      const next = searchParams.get("next");
      if (isSafeNextPath(next)) {
        router.replace(next as string);
        return;
      }

      if (whoami.is_admin) {
        router.replace("/admin");
        return;
      }
      if (whoami.student_id) {
        router.replace(`/student/${whoami.student_id}`);
        return;
      }
      router.replace("/");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-md">
        <Card title="Sign In">
          <form className="grid gap-4" onSubmit={handleSubmit}>
            <label className="grid gap-1 text-sm">
              <span className="text-slate-500">Username</span>
              <input
                className="border rounded px-3 py-2"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                required
              />
            </label>
            <label className="grid gap-1 text-sm">
              <span className="text-slate-500">Password</span>
              <input
                className="border rounded px-3 py-2"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </label>
            <button
              type="submit"
              className="bg-slate-900 text-white rounded px-4 py-2 text-sm"
              disabled={loading}
            >
              {loading ? "Signing in..." : "Sign In"}
            </button>
          </form>
        </Card>
        {error && <div className="mt-4"><ErrorState message={error} /></div>}
      </div>
    </div>
  );
}
