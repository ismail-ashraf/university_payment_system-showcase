"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import type { PaymentDetail } from "@/lib/types";
import { Card } from "@/components/Card";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { PaymentStatusBadge } from "@/components/PaymentStatusBadge";

export default function PaymentDetailPage({
  params,
}: {
  params: { studentId: string; paymentId: string };
}) {
  const { studentId, paymentId } = params;
  const [data, setData] = useState<PaymentDetail | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const res = await apiGet<PaymentDetail>(
          `/api/students/${studentId}/payments/${paymentId}/`
        );
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
  }, [studentId, paymentId]);

  if (loading) return <LoadingState />;
  if (error) return <ErrorState message={error} />;
  if (!data) return <ErrorState message="Payment not found." />;

  return (
    <Card title="Payment Detail">
      <div className="grid md:grid-cols-2 gap-4 text-sm">
        <div>
          <p className="text-slate-500">Transaction</p>
          <p className="font-medium">{data.transaction_id}</p>
        </div>
        <div>
          <p className="text-slate-500">Status</p>
          <PaymentStatusBadge status={data.status} />
        </div>
        <div>
          <p className="text-slate-500">Amount</p>
          <p className="font-medium">{data.amount} EGP</p>
        </div>
        <div>
          <p className="text-slate-500">Semester</p>
          <p className="font-medium">{data.semester}</p>
        </div>
        <div>
          <p className="text-slate-500">Provider</p>
          <p className="font-medium">{data.payment_method || "—"}</p>
        </div>
        <div>
          <p className="text-slate-500">Gateway Reference</p>
          <p className="font-medium">{data.gateway_reference || "—"}</p>
        </div>
        <div>
          <p className="text-slate-500">Created</p>
          <p className="font-medium">{new Date(data.created_at).toLocaleString()}</p>
        </div>
        <div>
          <p className="text-slate-500">Updated</p>
          <p className="font-medium">{new Date(data.updated_at).toLocaleString()}</p>
        </div>
      </div>
    </Card>
  );
}
