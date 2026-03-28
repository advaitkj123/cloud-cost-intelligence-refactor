import { RefreshCw } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { api } from '../lib/api';
import type { AwsSyncResponse, ResourceSummary } from '../types';
import { ErrorState } from '../components/ErrorState';
import { LoadingState } from '../components/LoadingState';
import { Panel } from '../components/Panel';
import { StatusBadge } from '../components/StatusBadge';

export function AwsResourcesPage() {
  const [resources, setResources] = useState<ResourceSummary[]>([]);
  const [syncResult, setSyncResult] = useState<AwsSyncResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    const response = await api.getAwsResources();
    setResources(response);
  };

  useEffect(() => {
    let active = true;

    const boot = async () => {
      try {
        const response = await api.getAwsResources();
        if (active) {
          setResources(response);
          setError(null);
        }
      } catch (err) {
        if (active) {
          setError(err instanceof Error ? err.message : 'Failed to load AWS resources');
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    };

    boot();
    const interval = window.setInterval(() => {
      if (active) {
        load().catch(() => undefined);
      }
    }, 15000);

    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);

  const onSync = async () => {
    try {
      setSyncing(true);
      const result = await api.syncAws();
      setSyncResult(result);
      await load();
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'AWS sync failed');
    } finally {
      setSyncing(false);
      setLoading(false);
    }
  };

  const runningCount = useMemo(
    () => resources.filter((resource) => (resource.cloud_state ?? resource.status) === 'running').length,
    [resources],
  );

  if (loading) return <LoadingState />;
  if (error && resources.length === 0) return <ErrorState message={error} />;

  return (
    <div className="space-y-6">
      <Panel
        title="AWS EC2 resources"
        subtitle="Real EC2 inventory, CloudWatch metrics, and hourly pricing ingested from AWS"
      >
        <div className="mb-5 flex flex-wrap items-center justify-between gap-4">
          <div className="flex flex-wrap gap-6 text-sm text-slate-300">
            <div>
              <span className="text-slate-500">Instances:</span> {resources.length}
            </div>
            <div>
              <span className="text-slate-500">Running:</span> {runningCount}
            </div>
            {syncResult ? (
              <div>
                <span className="text-slate-500">Last sync:</span> {syncResult.resources_synced} resources / {syncResult.metrics_ingested} metrics
              </div>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onSync}
            disabled={syncing}
            className="inline-flex items-center gap-2 rounded-2xl bg-blue-500 px-4 py-2 text-sm font-medium text-white shadow-lg shadow-blue-500/20 transition hover:bg-blue-400 disabled:cursor-not-allowed disabled:bg-blue-500/60"
          >
            <RefreshCw className={`h-4 w-4 ${syncing ? 'animate-spin' : ''}`} />
            {syncing ? 'Syncing AWS...' : 'Sync AWS'}
          </button>
        </div>

        {error ? <div className="mb-4 rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">{error}</div> : null}

        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="text-slate-400">
              <tr>
                <th className="pb-4">Name</th>
                <th className="pb-4">Instance ID</th>
                <th className="pb-4">Type</th>
                <th className="pb-4">Region</th>
                <th className="pb-4">State</th>
                <th className="pb-4">Cost/hr</th>
                <th className="pb-4">Latest Cost</th>
                <th className="pb-4">CPU</th>
                <th className="pb-4">Network In</th>
                <th className="pb-4">Network Out</th>
              </tr>
            </thead>
            <tbody>
              {resources.map((resource) => (
                <tr key={resource.id} className="border-t border-slate-800 text-slate-200">
                  <td className="py-4 font-medium">{resource.tags.Name ?? '—'}</td>
                  <td className="py-4 font-mono text-xs text-slate-300">{resource.external_id ?? resource.name}</td>
                  <td className="py-4 text-slate-300">{resource.instance_type ?? '—'}</td>
                  <td className="py-4 text-slate-400">{resource.region}</td>
                  <td className="py-4"><StatusBadge status={resource.cloud_state ?? resource.status} /></td>
                  <td className="py-4">${(resource.cost_per_hour ?? 0).toFixed(4)}</td>
                  <td className="py-4">${(resource.latest_cost ?? 0).toFixed(4)}</td>
                  <td className="py-4">{resource.latest_cpu?.toFixed(2) ?? '—'}%</td>
                  <td className="py-4">{resource.latest_network_in?.toFixed(0) ?? '—'}</td>
                  <td className="py-4">{resource.latest_network_out?.toFixed(0) ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
