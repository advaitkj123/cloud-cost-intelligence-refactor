import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { CostSummary } from '../types';

export function ResourceCostBarChart({ data }: { data: CostSummary['per_resource'] }) {
  return (
    <div className="h-80 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data.slice(0, 8)}>
          <XAxis dataKey="resource_name" stroke="#94a3b8" tickLine={false} axisLine={false} />
          <YAxis stroke="#94a3b8" tickLine={false} axisLine={false} />
          <Tooltip
            contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #1e293b', borderRadius: '16px' }}
            formatter={(value: number) => [`$${value.toFixed(4)}`, 'Accumulated cost']}
          />
          <Bar dataKey="total_cost" fill="#10b981" radius={[10, 10, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
