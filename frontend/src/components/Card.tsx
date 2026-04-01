export function Card({ title, children }: { title?: string; children: React.ReactNode }) {
  return (
    <section className="bg-white border border-slate-200 rounded-lg p-5">
      {title ? <h2 className="text-lg font-semibold mb-3">{title}</h2> : null}
      {children}
    </section>
  );
}
