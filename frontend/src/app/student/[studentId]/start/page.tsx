"use client";

import { useState } from "react";
import { apiPost } from "@/lib/api";
import { Card } from "@/components/Card";
import { ErrorState } from "@/components/ErrorState";

type StartResult = {
  transaction_id: string;
  status: string;
  provider?: string;
  transaction_reference?: string;
};

export default function StartPaymentPage({ params }: { params: { studentId: string } }) {
  const { studentId } = params;
  const [provider, setProvider] = useState<string>("");
  const [result, setResult] = useState<StartResult | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setResult(null);
    setLoading(true);
    try {
      const body = provider ? { provider } : {};
      const data = await apiPost<StartResult>(
        `/api/students/${studentId}/payments/start/`,
        body
      );
      setResult(data);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card title="Start Payment">
      <form className="space-y-4" onSubmit={submit}>
        <div>
          <label className="block text-sm font-medium mb-1">Provider (optional)</label>
          <select
            className="w-full border border-slate-300 rounded px-3 py-2"
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
          >
            <option value="">No provider (create pending)</option>
            <option value="fawry">Fawry</option>
            <option value="vodafone">Vodafone Cash</option>
            <option value="bank">Bank Transfer</option>
          </select>
        </div>

        <button
          className="bg-ocean text-white rounded px-4 py-2 disabled:opacity-60"
          disabled={loading}
        >
          {loading ? "Starting..." : "Start Payment"}
        </button>
      </form>

      {error ? <div className="mt-4"><ErrorState message={error} /></div> : null}

      {result ? (
        <div className="mt-4 bg-slate-50 border border-slate-200 rounded p-4 text-sm">
          <p><span className="text-slate-500">Transaction:</span> {result.transaction_id}</p>
          <p><span className="text-slate-500">Status:</span> {result.status}</p>
          {result.transaction_reference ? (
            <p><span className="text-slate-500">Reference:</span> {result.transaction_reference}</p>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}
