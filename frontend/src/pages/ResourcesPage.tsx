import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import type { ResourceSummary } from '../types';
import { ErrorState } from '../components/ErrorState';
import { LoadingState } from '../components/LoadingState';
import { Panel } from '../components/Panel';
import { StatusBadge } from '../components/StatusBadge';

export function ResourcesPage() {
  const [resources, setResources] = useState<ResourceSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const response = await api.getResources();
        if (active) {
          setResources(response);
          setError(null);
        }
      } catch (err) {
        if (active) {
          setError(err instanceof Error ? err.message : 'Failed to load resources');
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    };

    load();
    const interval = window.setInterval(load, 10000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);

  if (loading) return <LoadingState />;
  if (error) return <ErrorState message={error} />;

  return (
    <Panel title="Monitored resources" subtitle="Unified resource inventory across simulated and AWS-connected assets">
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="text-slate-400">
            <tr>
              <th className="pb-4">Resource</th>
              <th className="pb-4">Provider</th>
              <th className="pb-4">Type</th>
              <th className="pb-4">Region</th>
              <th className="pb-4">Status</th>
              <th className="pb-4">Cost/hr</th>
              <th className="pb-4">Latest Cost</th>
              <th className="pb-4">CPU</th>
              <th className="pb-4">Net In</th>
              <th className="pb-4">Net Out</th>
            </tr>
          </thead>
          <tbody>
            {resources.map((resource) => (
              <tr key={resource.id} className="border-t border-slate-800 text-slate-200">
                <td className="py-4 font-medium">{resource.tags.Name ?? resource.name}</td>
                <td className="py-4 uppercase text-slate-400">{resource.provider}</td>
                <td className="py-4 uppercase text-slate-400">{resource.instance_type ?? resource.type}</td>
                <td className="py-4 text-slate-400">{resource.region}</td>
                <td className="py-4"><StatusBadge status={resource.cloud_state ?? resource.status} /></td>
                <td className="py-4">${(resource.cost_per_hour ?? 0).toFixed(4)}</td>
                <td className="py-4">${(resource.latest_cost ?? 0).toFixed(4)}</td>
                <td className="py-4">{resource.latest_cpu?.toFixed(1) ?? '—'}%</td>
                <td className="py-4">{resource.latest_network_in?.toFixed(0) ?? '—'}</td>
                <td className="py-4">{resource.latest_network_out?.toFixed(0) ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
