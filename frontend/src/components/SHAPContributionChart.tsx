import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { SHAPContribution } from '../types';

const positiveColor = '#22d3ee';
const negativeColor = '#fb7185';

export function SHAPContributionChart({ data }: { data: SHAPContribution[] }) {
  const chartData = [...data]
    .sort((left, right) => Math.abs(right.contribution) - Math.abs(left.contribution))
    .slice(0, 6)
    .reverse();

  if (chartData.length === 0) {
    return <div className="rounded-2xl border border-dashed border-white/10 px-4 py-8 text-sm text-slate-400">No SHAP contributions are available for this anomaly yet.</div>;
  }

  return (
    <div className="h-72 w-full">
      <ResponsiveContainer>
        <BarChart data={chartData} layout="vertical" margin={{ top: 8, right: 24, left: 12, bottom: 0 }}>
          <CartesianGrid stroke="rgba(148,163,184,0.12)" horizontal={false} />
          <XAxis type="number" tick={{ fill: '#94a3b8', fontSize: 12 }} axisLine={false} tickLine={false} />
          <YAxis
            type="category"
            dataKey="feature_label"
            width={120}
            tick={{ fill: '#e2e8f0', fontSize: 12 }}
            axisLine={false}
            tickLine={false}
          />
          <ReferenceLine x={0} stroke="rgba(148,163,184,0.35)" />
          <Tooltip
            cursor={{ fill: 'rgba(255,255,255,0.04)' }}
            contentStyle={{
              backgroundColor: 'rgba(2, 6, 23, 0.95)',
              border: '1px solid rgba(255,255,255,0.08)',
              borderRadius: '16px',
              color: '#e2e8f0',
            }}
            formatter={(value: number) => [value.toFixed(4), 'SHAP impact']}
            labelFormatter={(_, payload) => {
              const item = payload?.[0]?.payload as SHAPContribution | undefined;
              return item ? `${item.feature_label}: ${item.feature_value ?? 'n/a'}` : 'Contribution';
            }}
          />
          <Bar dataKey="contribution" radius={[8, 8, 8, 8]}>
            {chartData.map((entry) => (
              <Cell key={entry.feature} fill={entry.contribution >= 0 ? positiveColor : negativeColor} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
