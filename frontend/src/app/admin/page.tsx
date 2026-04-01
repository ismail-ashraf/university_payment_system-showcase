"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import type { AdminPaymentSummary, PaymentItem } from "@/lib/types";
import { Card } from "@/components/Card";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { PaymentStatusBadge } from "@/components/PaymentStatusBadge";

type RecentPaymentsResponse = {
  total_records: number;
  payments: PaymentItem[];
};

export default function AdminOverviewPage() {
  const [summary, setSummary] = useState<AdminPaymentSummary | null>(null);
  const [recent, setRecent] = useState<RecentPaymentsResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const [summaryData, recentData] = await Promise.all([
          apiGet<AdminPaymentSummary>("/api/admin/payments/summary/"),
          apiGet<RecentPaymentsResponse>("/api/admin/payments/recent/"),
        ]);
        if (!active) return;
        setSummary(summaryData);
        setRecent(recentData);
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
  }, []);

  if (loading) return <LoadingState />;
  if (error) return <ErrorState message={error} />;
  if (!summary || !recent) return <ErrorState message="Failed to load admin data." />;

  return (
    <div className="grid gap-6">
      <div className="grid md:grid-cols-3 gap-4">
        <Card title="Total Payments">
          <p className="text-3xl font-semibold">{summary.total_count}</p>
        </Card>
        <Card title="Total Paid Amount">
          <p className="text-3xl font-semibold">{summary.total_paid_amount}</p>
        </Card>
        <Card title="Status Counts">
          <div className="grid gap-2 text-sm">
            {Object.keys(summary.status_counts).length === 0 ? (
              <p className="text-slate-500">No payments yet.</p>
            ) : (
              Object.entries(summary.status_counts).map(([status, count]) => (
                <div key={status} className="flex items-center justify-between">
                  <span className="text-slate-600">{status}</span>
                  <span className="font-medium">{count}</span>
                </div>
              ))
            )}
          </div>
        </Card>
      </div>

      <Card title="Recent Payments">
        {recent.payments.length === 0 ? (
          <EmptyState message="No recent payments found." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-slate-500">
                <tr>
                  <th className="text-left py-2">Transaction</th>
                  <th className="text-left py-2">Student</th>
                  <th className="text-left py-2">Amount</th>
                  <th className="text-left py-2">Status</th>
                  <th className="text-left py-2">Gateway</th>
                  <th className="text-left py-2">Created</th>
                </tr>
              </thead>
              <tbody>
                {recent.payments.map((payment) => (
                  <tr key={payment.transaction_id} className="border-t border-slate-100">
                    <td className="py-2 font-mono text-xs">{payment.transaction_id}</td>
                    <td className="py-2">
                      {payment.student_name} ({payment.student_id})
                    </td>
                    <td className="py-2">{payment.amount}</td>
                    <td className="py-2">
                      <PaymentStatusBadge status={payment.status} />
                    </td>
                    <td className="py-2">{payment.payment_method || "—"}</td>
                    <td className="py-2">{new Date(payment.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
