"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import type { PaymentItem, StudentProfile } from "@/lib/types";
import { Card } from "@/components/Card";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { PaymentStatusBadge } from "@/components/PaymentStatusBadge";

type PaymentsResponse = {
  student_id: string;
  student_name: string;
  total_records: number;
  payments: PaymentItem[];
};

export default function StudentDashboard({ params }: { params: { studentId: string } }) {
  const { studentId } = params;
  const [profile, setProfile] = useState<StudentProfile | null>(null);
  const [payments, setPayments] = useState<PaymentsResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const [p, pay] = await Promise.all([
          apiGet<StudentProfile>(`/api/students/${studentId}/profile/`),
          apiGet<PaymentsResponse>(`/api/students/${studentId}/payments/`),
        ]);
        if (!active) return;
        setProfile(p);
        setPayments(pay);
      } catch (err) {
        if (!active) return;
        setError((err as Error).message);
      } finally {
        if (active) setLoading(false);
      }
    }
    load();
    return () => {
      active = false;
    };
  }, [studentId]);

  if (loading) return <LoadingState />;
  if (error) return <ErrorState message={error} />;
  if (!profile || !payments) return <ErrorState message="Failed to load data." />;

  const latest = payments.payments[0];

  return (
    <div className="grid gap-6">
      <Card title="Student Profile">
        <div className="grid md:grid-cols-2 gap-3 text-sm">
          <div>
            <p className="text-slate-500">Name</p>
            <p className="font-medium">{profile.name}</p>
          </div>
          <div>
            <p className="text-slate-500">Status</p>
            <p className="font-medium">{profile.status}</p>
          </div>
          <div>
            <p className="text-slate-500">Faculty</p>
            <p className="font-medium">{profile.faculty || "—"}</p>
          </div>
          <div>
            <p className="text-slate-500">Allowed Hours</p>
            <p className="font-medium">{profile.allowed_hours}</p>
          </div>
        </div>
      </Card>

      <Card title="Payment Summary">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-slate-500 text-sm">Total payments</p>
            <p className="text-2xl font-semibold">{payments.total_records}</p>
          </div>
          <div className="text-right">
            <p className="text-slate-500 text-sm">Latest status</p>
            {latest ? <PaymentStatusBadge status={latest.status} /> : <span>—</span>}
          </div>
        </div>
      </Card>
    </div>
  );
}
