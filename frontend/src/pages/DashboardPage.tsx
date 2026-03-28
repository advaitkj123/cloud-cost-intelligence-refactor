import { Cloud, DollarSign, PiggyBank, TrendingUp } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import type { CostSummary, ResourceSummary } from '../types';
import { CostTrendChart } from '../components/CostTrendChart';
import { ErrorState } from '../components/ErrorState';
import { LoadingState } from '../components/LoadingState';
import { Panel } from '../components/Panel';
import { ResourceCostBarChart } from '../components/ResourceCostBarChart';
import { StatCard } from '../components/StatCard';

export function DashboardPage() {
  const [data, setData] = useState<CostSummary | null>(null);
  const [resources, setResources] = useState<ResourceSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    const load = async () => {
      try {
        const [summary, resourceList] = await Promise.all([api.getCost(), api.getResources()]);
        if (active) {
          setData(summary);
          setResources(resourceList);
          setError(null);
        }
      } catch (err) {
        if (active) {
          setError(err instanceof Error ? err.message : 'Failed to load dashboard');
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
  if (error || !data) return <ErrorState message={error ?? 'Dashboard unavailable'} />;

  const awsResources = resources.filter((resource) => resource.provider === 'aws');

  return (
    <div className="space-y-6">
      <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
        <StatCard title="Total Cost" value={`$${data.total_cost.toFixed(2)}`} hint="Accumulated cost from ingested cloud usage" icon={<DollarSign className="h-5 w-5" />} />
        <StatCard title="Projected Monthly Cost" value={`$${data.projected_monthly_cost.toFixed(2)}`} hint="Forecast based on current run rate" icon={<TrendingUp className="h-5 w-5" />} />
        <StatCard title="Tracked Savings" value={`$${data.total_savings.toFixed(2)}`} hint="Dry-run or executed optimization savings" icon={<PiggyBank className="h-5 w-5" />} />
        <StatCard title="AWS Resources" value={`${awsResources.length}`} hint="Discovered EC2 instances connected to the platform" icon={<Cloud className="h-5 w-5" />} />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.4fr,1fr]">
        <Panel title="Cost trend" subtitle="Live cost trajectory based on ingested usage and EC2 runtime pricing">
          <CostTrendChart data={data.trend} />
        </Panel>
        <Panel title="Top cost contributors" subtitle="Resources driving the largest share of current cloud spend">
          <ResourceCostBarChart data={data.per_resource} />
        </Panel>
      </div>
    </div>
  );
}
