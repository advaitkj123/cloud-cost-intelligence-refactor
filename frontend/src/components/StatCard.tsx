import type { ReactNode } from 'react';

export function StatCard({ title, value, hint, icon }: { title: string; value: string; hint: string; icon: ReactNode }) {
  return (
    <div className="rounded-3xl border border-slate-800 bg-slate-900/60 p-6 shadow-panel backdrop-blur">
      <div className="flex items-center justify-between">
        <span className="text-sm text-slate-400">{title}</span>
        <div className="rounded-2xl bg-slate-800 p-3 text-blue-300">{icon}</div>
      </div>
      <div className="mt-4 text-3xl font-semibold text-white">{value}</div>
      <p className="mt-2 text-sm text-slate-400">{hint}</p>
    </div>
  );
}
