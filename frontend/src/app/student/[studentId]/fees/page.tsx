"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import type { FeeBreakdown } from "@/lib/types";
import { Card } from "@/components/Card";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";

export default function FeesPage({ params }: { params: { studentId: string } }) {
  const { studentId } = params;
  const [fees, setFees] = useState<FeeBreakdown | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const data = await apiGet<FeeBreakdown>(`/api/students/${studentId}/fees/`);
        if (!active) return;
        setFees(data);
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
  if (!fees) return <ErrorState message="No fee data found." />;

  return (
    <Card title="Fee Breakdown">
      <div className="space-y-3">
        {fees.line_items.map((item, idx) => (
          <div key={idx} className="flex items-center justify-between text-sm">
            <span>{item.label}</span>
            <span>{item.amount} {fees.currency}</span>
          </div>
        ))}
        <div className="flex items-center justify-between border-t pt-3 font-semibold">
          <span>Total</span>
          <span>{fees.total} {fees.currency}</span>
        </div>
      </div>
    </Card>
  );
}
