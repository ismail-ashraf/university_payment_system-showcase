export function LoadingState({ label = "Loading..." }: { label?: string }) {
  return (
    <div className="text-slate-500 text-sm py-6">{label}</div>
  );
}
