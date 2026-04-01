"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import { Card } from "@/components/Card";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { PaymentStatusBadge } from "@/components/PaymentStatusBadge";

type StudentStatus = {
  student_id: string;
  can_start_payment: boolean;
  reason_code: string | null;
  current_payment: {
    transaction_id: string;
    status: string;
    amount: string;
    created_at: string;
    expires_at?: string;
  } | null;
};

type StudentNextAction = {
  next_action: "submit" | "wait" | "none";
  reason_code: string | null;
};

type StudentPaymentItem = {
  transaction_id: string;
  status: string;
  amount: string;
  created_at: string;
  expires_at?: string;
};

type StudentPaymentsResponse = {
  payments: StudentPaymentItem[];
};

export default function StudentPaymentsOverviewPage() {
  const [status, setStatus] = useState<StudentStatus | null>(null);
  const [nextAction, setNextAction] = useState<StudentNextAction | null>(null);
  const [payments, setPayments] = useState<StudentPaymentItem[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const [statusData, actionData, paymentsData] = await Promise.all([
          apiGet<StudentStatus>("/api/payments/student/status/"),
          apiGet<StudentNextAction>("/api/payments/student/next-action/"),
          apiGet<StudentPaymentsResponse>("/api/payments/student/payments/"),
        ]);
        if (!active) return;
        setStatus(statusData);
        setNextAction(actionData);
        setPayments(paymentsData.payments || []);
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
  if (!status || !nextAction) return <ErrorState message="Failed to load payments." />;

  const current = status.current_payment;

  return (
    <div className="grid gap-6">
      <div className="grid md:grid-cols-3 gap-4">
        <Card title="Payment Status">
          <p className="text-sm text-slate-600">Can start payment</p>
          <p className="text-2xl font-semibold">
            {status.can_start_payment ? "Yes" : "No"}
          </p>
          {status.reason_code && (
            <p className="text-xs text-slate-500 mt-2">
              Reason: {status.reason_code}
            </p>
          )}
          {current && (
            <div className="mt-3 text-sm text-slate-600">
              <div>Status: <PaymentStatusBadge status={current.status} /></div>
              <div>Amount: {current.amount}</div>
              <div>Created: {new Date(current.created_at).toLocaleString()}</div>
            </div>
          )}
        </Card>

        <Card title="Next Action">
          <p className="text-2xl font-semibold capitalize">{nextAction.next_action}</p>
          {nextAction.reason_code && (
            <p className="text-xs text-slate-500 mt-2">
              Reason: {nextAction.reason_code}
            </p>
          )}
        </Card>

        <Card title="Current Payment">
          {current ? (
            <div className="text-sm text-slate-600">
              <div className="font-mono text-xs">{current.transaction_id}</div>
              <div className="mt-1">Status: <PaymentStatusBadge status={current.status} /></div>
              <div>Amount: {current.amount}</div>
              {current.expires_at && (
                <div>Expires: {new Date(current.expires_at).toLocaleString()}</div>
              )}
            </div>
          ) : (
            <p className="text-sm text-slate-500">No active payment.</p>
          )}
        </Card>
      </div>

      <Card title="Recent Payments">
        {payments.length === 0 ? (
          <EmptyState message="No recent payments found." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-slate-500">
                <tr>
                  <th className="text-left py-2">Transaction</th>
                  <th className="text-left py-2">Amount</th>
                  <th className="text-left py-2">Status</th>
                  <th className="text-left py-2">Created</th>
                  <th className="text-left py-2">Expires</th>
                </tr>
              </thead>
              <tbody>
                {payments.map((payment) => (
                  <tr key={payment.transaction_id} className="border-t border-slate-100">
                    <td className="py-2 font-mono text-xs">
                      <a
                        href={`/payments/${payment.transaction_id}`}
                        className="text-sky-700 hover:underline"
                      >
                        {payment.transaction_id}
                      </a>
                    </td>
                    <td className="py-2">{payment.amount}</td>
                    <td className="py-2">
                      <PaymentStatusBadge status={payment.status} />
                    </td>
                    <td className="py-2">
                      {new Date(payment.created_at).toLocaleString()}
                    </td>
                    <td className="py-2">
                      {payment.expires_at
                        ? new Date(payment.expires_at).toLocaleString()
                        : "-"}
                    </td>
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
