"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { apiGet, apiPost } from "@/lib/api";

export default function HomePage() {
  const router = useRouter();
  const [studentId, setStudentId] = useState("");
  const [nationalId, setNationalId] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    apiGet("/api/students/verify/status/").catch(() => {});
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleaned = studentId.trim().toUpperCase();
    const national = nationalId.trim();
    if (!cleaned || !national) {
      setError("Student ID and National ID are required.");
      return;
    }
    try {
      await apiPost("/api/students/verify/", {
        student_id: cleaned,
        national_id: national,
      });
      router.push(`/student/${encodeURIComponent(cleaned)}`);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <div className="w-full max-w-md bg-white shadow-sm rounded-lg p-6 border border-slate-200">
        <h1 className="text-2xl font-semibold">Student Payment Portal</h1>
        <p className="text-slate-600 mt-2">Enter your student ID to continue.</p>

        <form className="mt-6 space-y-3" onSubmit={submit}>
          <label className="block text-sm font-medium">Student ID</label>
          <input
            className="w-full rounded border border-slate-300 px-3 py-2"
            value={studentId}
            onChange={(e) => {
              setStudentId(e.target.value);
              setError("");
            }}
            placeholder="e.g. 20210001"
          />
          <label className="block text-sm font-medium">National ID</label>
          <input
            className="w-full rounded border border-slate-300 px-3 py-2"
            value={nationalId}
            onChange={(e) => {
              setNationalId(e.target.value);
              setError("");
            }}
            placeholder="e.g. 29501011234567"
          />
          {error ? <p className="text-sm text-red-600">{error}</p> : null}
          <button className="w-full bg-ocean text-white rounded py-2">Continue</button>
        </form>
      </div>
    </main>
  );
}
