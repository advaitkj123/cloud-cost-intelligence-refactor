import { NavLink, Outlet } from 'react-router-dom';
import { Activity, AlertTriangle, Cloud, DollarSign, PlaySquare, Server, Sparkles } from 'lucide-react';

const links = [
  { to: '/', label: 'Executive Overview', icon: Activity },
  { to: '/resources', label: 'Resources', icon: Cloud },
  { to: '/aws/resources', label: 'AWS EC2', icon: Server },
  { to: '/anomalies', label: 'Anomalies', icon: AlertTriangle },
  { to: '/actions', label: 'Actions', icon: PlaySquare },
];

export function Layout() {
  return (
    <div className="min-h-screen text-slate-100">
      <div className="mx-auto flex max-w-[1600px] gap-6 px-6 py-8">
        <aside className="sticky top-8 h-[calc(100vh-4rem)] w-80 rounded-[28px] border border-white/10 bg-slate-950/70 p-6 shadow-[0_25px_120px_-60px_rgba(34,211,238,0.45)] backdrop-blur-xl">
          <div className="mb-8 rounded-[24px] border border-cyan-400/15 bg-gradient-to-br from-cyan-400/10 via-transparent to-indigo-500/10 p-5">
            <div className="mb-4 flex items-center gap-3">
              <div className="rounded-2xl bg-cyan-400/15 p-3 text-cyan-300">
                <DollarSign className="h-6 w-6" />
              </div>
              <div>
                <h1 className="text-lg font-semibold">Cost Intelligence</h1>
                <p className="text-sm text-slate-400">Enterprise FinOps control plane</p>
              </div>
            </div>
            <div className="flex items-center gap-2 rounded-2xl border border-white/10 bg-white/[0.03] px-3 py-2 text-xs uppercase tracking-[0.22em] text-slate-300">
              <Sparkles className="h-4 w-4 text-cyan-300" />
              Explainable cloud anomaly detection
            </div>
          </div>

          <nav className="space-y-2">
            {links.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                className={({ isActive }) =>
                  `flex items-center gap-3 rounded-2xl px-4 py-3 text-sm transition ${
                    isActive
                      ? 'border border-cyan-400/20 bg-cyan-400/10 text-white shadow-[0_0_0_1px_rgba(34,211,238,0.15)]'
                      : 'border border-transparent text-slate-300 hover:border-white/10 hover:bg-white/[0.03] hover:text-white'
                  }`
                }
              >
                <Icon className="h-4 w-4" />
                <span>{label}</span>
              </NavLink>
            ))}
          </nav>
        </aside>

        <main className="flex-1">
          <header className="mb-6 rounded-[28px] border border-white/10 bg-slate-950/60 p-7 shadow-[0_25px_120px_-60px_rgba(99,102,241,0.5)] backdrop-blur-xl">
            <p className="text-sm uppercase tracking-[0.3em] text-cyan-300">Executive Cloud FinOps</p>
            <h2 className="mt-3 text-3xl font-semibold md:text-4xl">Cloud Cost Intelligence Platform</h2>
            <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-400">
              Predict cloud spend, surface explainable anomalies, and orchestrate optimization workflows with a SaaS-grade,
              operator-first control plane inspired by modern enterprise observability products.
            </p>
          </header>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
