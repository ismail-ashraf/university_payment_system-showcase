"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiGet } from "@/lib/api";
import type { AdminPaymentListResponse, PaymentItem } from "@/lib/types";
import { Card } from "@/components/Card";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { PaymentStatusBadge } from "@/components/PaymentStatusBadge";

type Filters = {
  status: string;
  provider: string;
  student_id: string;
  semester: string;
  date_from: string;
  date_to: string;
  page: number;
  page_size: number;
};

const initialFilters: Filters = {
  status: "",
  provider: "",
  student_id: "",
  semester: "",
  date_from: "",
  date_to: "",
  page: 1,
  page_size: 20,
};

function buildQuery(filters: Filters) {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.provider) params.set("provider", filters.provider);
  if (filters.student_id) params.set("student_id", filters.student_id);
  if (filters.semester) params.set("semester", filters.semester);
  if (filters.date_from) params.set("date_from", filters.date_from);
  if (filters.date_to) params.set("date_to", filters.date_to);
  params.set("page", String(filters.page));
  params.set("page_size", String(filters.page_size));
  return params.toString();
}

export default function AdminPaymentsPage() {
  const [filters, setFilters] = useState<Filters>(initialFilters);
  const [data, setData] = useState<AdminPaymentListResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);

  const query = useMemo(() => buildQuery(filters), [filters]);

  useEffect(() => {
    let active = true;
    async function load() {
      setLoading(true);
      try {
        const response = await apiGet<AdminPaymentListResponse>(
          `/api/admin/payments/?${query}`
        );
        if (!active) return;
        setData(response);
        setError("");
      } catch (err) {
        if (!active) return;
        setError((err as Error).message);
        setData(null);
      } finally {
        if (active) setLoading(false);
      }
    }
    load();
    return () => {
      active = false;
    };
  }, [query, refreshKey]);

  function updateFilter<K extends keyof Filters>(key: K, value: Filters[K]) {
    setFilters((prev) => ({ ...prev, [key]: value, page: 1 }));
  }

  function resetFilters() {
    setFilters(initialFilters);
    setRefreshKey((value) => value + 1);
  }

  function goToPage(next: number) {
    setFilters((prev) => ({ ...prev, page: next }));
  }

  const payments = data?.payments || [];
  const canPrev = (data?.page || 1) > 1;
  const canNext = data ? data.page * data.page_size < data.total_records : false;

  if (loading) return <LoadingState />;
  if (error) return <ErrorState message={error} />;

  return (
    <div className="grid gap-6">
      <Card title="Filters">
        <div className="grid md:grid-cols-3 gap-4 text-sm">
          <label className="grid gap-1">
            <span className="text-slate-500">Status</span>
            <input
              className="border rounded px-3 py-2"
              value={filters.status}
              onChange={(event) => updateFilter("status", event.target.value)}
              placeholder="paid / pending / failed"
            />
          </label>
          <label className="grid gap-1">
            <span className="text-slate-500">Provider</span>
            <input
              className="border rounded px-3 py-2"
              value={filters.provider}
              onChange={(event) => updateFilter("provider", event.target.value)}
              placeholder="fawry / vodafone"
            />
          </label>
          <label className="grid gap-1">
            <span className="text-slate-500">Student ID</span>
            <input
              className="border rounded px-3 py-2"
              value={filters.student_id}
              onChange={(event) => updateFilter("student_id", event.target.value)}
              placeholder="20210001"
            />
          </label>
          <label className="grid gap-1">
            <span className="text-slate-500">Semester</span>
            <input
              className="border rounded px-3 py-2"
              value={filters.semester}
              onChange={(event) => updateFilter("semester", event.target.value)}
              placeholder="Fall 2026"
            />
          </label>
          <label className="grid gap-1">
            <span className="text-slate-500">Date From</span>
            <input
              className="border rounded px-3 py-2"
              value={filters.date_from}
              onChange={(event) => updateFilter("date_from", event.target.value)}
              placeholder="YYYY-MM-DD"
            />
          </label>
          <label className="grid gap-1">
            <span className="text-slate-500">Date To</span>
            <input
              className="border rounded px-3 py-2"
              value={filters.date_to}
              onChange={(event) => updateFilter("date_to", event.target.value)}
              placeholder="YYYY-MM-DD"
            />
          </label>
        </div>
        <div className="mt-4 flex items-center gap-3">
          <button
            className="px-4 py-2 rounded bg-slate-900 text-white text-sm"
            onClick={() => setRefreshKey((value) => value + 1)}
          >
            Apply Filters
          </button>
          <button
            className="px-4 py-2 rounded border text-sm"
            onClick={resetFilters}
          >
            Clear
          </button>
        </div>
      </Card>

      <Card title="Payments">
        {payments.length === 0 ? (
          <EmptyState message="No payments found for the selected filters." />
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
                {payments.map((payment: PaymentItem) => (
                  <tr key={payment.transaction_id} className="border-t border-slate-100">
                    <td className="py-2 font-mono text-xs">
                      <Link href={`/admin/payments/${payment.transaction_id}`}>
                        {payment.transaction_id}
                      </Link>
                    </td>
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

        {data && (
          <div className="mt-4 flex items-center justify-between text-sm">
            <p className="text-slate-500">
              Showing page {data.page} of{" "}
              {Math.max(1, Math.ceil(data.total_records / data.page_size))}
            </p>
            <div className="flex gap-2">
              <button
                className="px-3 py-1 border rounded disabled:opacity-50"
                onClick={() => goToPage((data.page || 1) - 1)}
                disabled={!canPrev}
              >
                Prev
              </button>
              <button
                className="px-3 py-1 border rounded disabled:opacity-50"
                onClick={() => goToPage((data.page || 1) + 1)}
                disabled={!canNext}
              >
                Next
              </button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
