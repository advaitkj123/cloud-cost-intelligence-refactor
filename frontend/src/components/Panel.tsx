import type { ReactNode } from 'react';

export function Panel({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <section className="rounded-3xl border border-slate-800 bg-slate-900/60 p-6 shadow-panel backdrop-blur">
      <div className="mb-6">
        <h3 className="text-lg font-semibold text-white">{title}</h3>
        {subtitle ? <p className="mt-1 text-sm text-slate-400">{subtitle}</p> : null}
      </div>
      {children}
    </section>
  );
}
