"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import type { AdminPaymentDetail } from "@/lib/types";
import { Card } from "@/components/Card";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { PaymentStatusBadge } from "@/components/PaymentStatusBadge";

export default function AdminPaymentDetailPage({
  params,
}: {
  params: { paymentId: string };
}) {
  const { paymentId } = params;
  const [payment, setPayment] = useState<AdminPaymentDetail | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const data = await apiGet<AdminPaymentDetail>(
          `/api/admin/payments/${paymentId}/`
        );
        if (!active) return;
        setPayment(data);
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
  }, [paymentId]);

  if (loading) return <LoadingState />;
  if (error) return <ErrorState message={error} />;
  if (!payment) return <ErrorState message="Payment not found." />;

  return (
    <div className="grid gap-6">
      <Card title="Payment Summary">
        <div className="grid md:grid-cols-3 gap-4 text-sm">
          <div>
            <p className="text-slate-500">Transaction ID</p>
            <p className="font-mono text-xs">{payment.transaction_id}</p>
          </div>
          <div>
            <p className="text-slate-500">Student</p>
            <p className="font-medium">
              {payment.student_name} ({payment.student_id})
            </p>
          </div>
          <div>
            <p className="text-slate-500">Status</p>
            <PaymentStatusBadge status={payment.status} />
          </div>
          <div>
            <p className="text-slate-500">Amount</p>
            <p className="font-medium">{payment.amount}</p>
          </div>
          <div>
            <p className="text-slate-500">Gateway</p>
            <p className="font-medium">{payment.payment_method || "—"}</p>
          </div>
          <div>
            <p className="text-slate-500">Semester</p>
            <p className="font-medium">{payment.semester}</p>
          </div>
          <div>
            <p className="text-slate-500">Used</p>
            <p className="font-medium">{payment.used ? "Yes" : "No"}</p>
          </div>
          <div>
            <p className="text-slate-500">Created</p>
            <p className="font-medium">
              {new Date(payment.created_at).toLocaleString()}
            </p>
          </div>
          <div>
            <p className="text-slate-500">Updated</p>
            <p className="font-medium">
              {new Date(payment.updated_at).toLocaleString()}
            </p>
          </div>
        </div>
      </Card>

      <Card title="Audit Logs">
        {payment.audit_logs.length === 0 ? (
          <EmptyState message="No audit logs recorded." />
        ) : (
          <div className="grid gap-3 text-sm">
            {payment.audit_logs.map((log) => (
              <div key={log.id} className="border border-slate-200 rounded p-3">
                <div className="flex items-center justify-between">
                  <p className="font-medium">{log.event_type}</p>
                  <p className="text-xs text-slate-500">
                    {new Date(log.created_at).toLocaleString()}
                  </p>
                </div>
                <div className="mt-2 grid md:grid-cols-3 gap-2 text-xs text-slate-600">
                  <span>Actor: {log.actor || "—"}</span>
                  <span>Amount: {log.amount || "—"}</span>
                  <span>ID: {log.id}</span>
                </div>
                {log.payload && (
                  <pre className="mt-2 bg-slate-50 p-2 rounded text-xs overflow-x-auto">
                    {JSON.stringify(log.payload, null, 2).slice(0, 500)}
                  </pre>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
