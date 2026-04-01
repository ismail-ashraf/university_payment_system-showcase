"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { apiGet } from "@/lib/api";
import { Card } from "@/components/Card";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { PaymentStatusBadge } from "@/components/PaymentStatusBadge";

type StudentPaymentDetail = {
  transaction_id: string;
  status: string;
  amount: string;
  created_at: string;
  expires_at?: string;
};

export default function StudentPaymentDetailPage() {
  const params = useParams<{ transactionId?: string }>();
  const transactionId = params?.transactionId;
  const [payment, setPayment] = useState<StudentPaymentDetail | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    async function load() {
      if (!transactionId) return;
      try {
        const data = await apiGet<StudentPaymentDetail>(
          `/api/payments/student/payments/${transactionId}/`
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
  }, [transactionId]);

  if (loading) return <LoadingState />;
  if (error) return <ErrorState message={error} />;
  if (!payment) return <ErrorState message="Payment not found." />;

  return (
    <div className="grid gap-6">
      <a href="/payments" className="text-sm text-sky-700 hover:underline">
        Back to payments
      </a>
      <Card title="Payment Detail">
        <div className="grid gap-2 text-sm text-slate-600">
          <div>
            <span className="font-medium text-slate-700">Transaction:</span>{" "}
            <span className="font-mono text-xs">{payment.transaction_id}</span>
          </div>
          <div>
            <span className="font-medium text-slate-700">Status:</span>{" "}
            <PaymentStatusBadge status={payment.status} />
          </div>
          <div>
            <span className="font-medium text-slate-700">Amount:</span>{" "}
            {payment.amount}
          </div>
          <div>
            <span className="font-medium text-slate-700">Created:</span>{" "}
            {new Date(payment.created_at).toLocaleString()}
          </div>
          {payment.expires_at && (
            <div>
              <span className="font-medium text-slate-700">Expires:</span>{" "}
              {new Date(payment.expires_at).toLocaleString()}
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
