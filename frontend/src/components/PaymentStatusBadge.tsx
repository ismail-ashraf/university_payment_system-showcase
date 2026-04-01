const COLOR: Record<string, string> = {
  paid: "bg-emerald-100 text-emerald-800",
  processing: "bg-sky-100 text-sky-800",
  pending: "bg-amber-100 text-amber-800",
  failed: "bg-red-100 text-red-800",
  cancelled: "bg-slate-100 text-slate-700",
  expired: "bg-slate-200 text-slate-800",
};

export function PaymentStatusBadge({ status }: { status: string }) {
  const key = status?.toLowerCase?.() || "pending";
  return (
    <span className={`px-2 py-1 text-xs rounded ${COLOR[key] || COLOR.pending}`}>
      {status}
    </span>
  );
}
