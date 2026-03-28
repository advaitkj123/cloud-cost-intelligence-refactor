import { useEffect, useMemo, useState } from 'react';
import { api } from '../lib/api';
import type { Action, ResourceSummary } from '../types';
import { ErrorState } from '../components/ErrorState';
import { LoadingState } from '../components/LoadingState';
import { Panel } from '../components/Panel';

export function ActionsPage() {
  const [actions, setActions] = useState<Action[]>([]);
  const [resources, setResources] = useState<ResourceSummary[]>([]);
  const [selectedResource, setSelectedResource] = useState<number>(0);
  const [selectedAction, setSelectedAction] = useState<string>('stop_instance');
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const options = useMemo(
    () => [
      { value: 'stop_instance', label: 'Stop instance' },
      { value: 'throttle_lambda', label: 'Throttle lambda' },
      { value: 'cleanup_storage', label: 'Cleanup storage' },
    ],
    []
  );

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const [actionsResponse, resourcesResponse] = await Promise.all([api.getActions(), api.getResources()]);
        if (active) {
          setActions(actionsResponse);
          setResources(resourcesResponse);
          setSelectedResource((current) => current || resourcesResponse[0]?.id || 0);
          setError(null);
        }
      } catch (err) {
        if (active) {
          setError(err instanceof Error ? err.message : 'Failed to load actions');
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

  const handleSubmit = async () => {
    if (!selectedResource) return;
    setSubmitting(true);
    setMessage('');
    try {
      const response = await api.triggerAction(selectedResource, selectedAction, true);
      setMessage(`Action queued in ${response.status} mode with estimated savings of $${response.estimated_savings.toFixed(4)}.`);
      const refreshed = await api.getActions();
      setActions(refreshed);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Failed to trigger action');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) return <LoadingState />;
  if (error) return <ErrorState message={error} />;

  return (
    <div className="space-y-6">
      <Panel title="Optimization command center" subtitle="Manually trigger mock optimization workflows in dry-run mode">
        <div className="grid gap-4 md:grid-cols-3">
          <select
            value={selectedResource}
            onChange={(event) => setSelectedResource(Number(event.target.value))}
            className="rounded-2xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-white outline-none"
          >
            {resources.map((resource) => (
              <option key={resource.id} value={resource.id}>{resource.name}</option>
            ))}
          </select>
          <select
            value={selectedAction}
            onChange={(event) => setSelectedAction(event.target.value)}
            className="rounded-2xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-white outline-none"
          >
            {options.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitting || !selectedResource}
            className="rounded-2xl bg-blue-500 px-4 py-3 text-sm font-medium text-white transition hover:bg-blue-400 disabled:cursor-not-allowed disabled:bg-slate-700"
          >
            {submitting ? 'Submitting...' : 'Trigger dry-run'}
          </button>
        </div>
        {message ? <p className="mt-4 text-sm text-slate-300">{message}</p> : null}
      </Panel>

      <Panel title="Action log" subtitle="Historical optimization events and modeled savings outcomes">
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="text-slate-400">
              <tr>
                <th className="pb-4">Resource</th>
                <th className="pb-4">Action</th>
                <th className="pb-4">Savings</th>
                <th className="pb-4">Timestamp</th>
              </tr>
            </thead>
            <tbody>
              {actions.map((action) => (
                <tr key={action.id} className="border-t border-slate-800 text-slate-200">
                  <td className="py-4">#{action.resource_id}</td>
                  <td className="py-4 capitalize">{action.action_type.split('_').join(' ')}</td>
                  <td className="py-4 text-emerald-300">${action.estimated_savings.toFixed(4)}</td>
                  <td className="py-4 text-slate-400">{new Date(action.timestamp).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
