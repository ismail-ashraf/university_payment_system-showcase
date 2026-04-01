"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import type { PaymentItem } from "@/lib/types";
import { Card } from "@/components/Card";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { PaymentStatusBadge } from "@/components/PaymentStatusBadge";

type PaymentsResponse = {
  student_id: string;
  student_name: string;
  total_records: number;
  payments: PaymentItem[];
};

export default function PaymentsPage({ params }: { params: { studentId: string } }) {
  const { studentId } = params;
  const [data, setData] = useState<PaymentsResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const res = await apiGet<PaymentsResponse>(`/api/students/${studentId}/payments/`);
        if (!active) return;
        setData(res);
      } catch (err) {
        if (!active) return;
        setError((err as Error).message);
      } finally {
        if (active) setLoading(false);
      }
    }
    load();
    return () => { active = false; };
  }, [studentId]);

  if (loading) return <LoadingState />;
  if (error) return <ErrorState message={error} />;
  if (!data || data.total_records === 0) return <EmptyState message="No payments yet." />;

  return (
    <Card title="Payments">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-slate-500">
            <tr className="text-left border-b">
              <th className="py-2">Transaction</th>
              <th className="py-2">Amount</th>
              <th className="py-2">Status</th>
              <th className="py-2">Semester</th>
            </tr>
          </thead>
          <tbody>
            {data.payments.map((p) => (
              <tr key={p.transaction_id} className="border-b">
                <td className="py-2">
                  <Link href={`/student/${studentId}/payments/${p.transaction_id}`}>
                    {p.transaction_id.slice(0, 8)}...
                  </Link>
                </td>
                <td className="py-2">{p.amount} EGP</td>
                <td className="py-2"><PaymentStatusBadge status={p.status} /></td>
                <td className="py-2">{p.semester}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
