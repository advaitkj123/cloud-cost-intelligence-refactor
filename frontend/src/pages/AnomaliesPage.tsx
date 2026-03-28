import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, BrainCircuit, Cloud, RefreshCw, Sparkles, TrendingUp } from 'lucide-react';
import { SHAPContributionChart } from '../components/SHAPContributionChart';
import { ErrorState } from '../components/ErrorState';
import { LoadingState } from '../components/LoadingState';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { api, queryKeys } from '../lib/api';
import { cn } from '../lib/utils';
import type { Anomaly } from '../types';

function severity(score: number) {
  if (score >= 0.75) return 'Critical';
  if (score >= 0.5) return 'High';
  if (score >= 0.3) return 'Medium';
  return 'Low';
}

function severityVariant(score: number): 'danger' | 'warning' | 'info' | 'success' {
  if (score >= 0.75) return 'danger';
  if (score >= 0.5) return 'warning';
  if (score >= 0.3) return 'info';
  return 'success';
}

const filters = ['All', 'Critical', 'High', 'Medium', 'Low'] as const;

export function AnomaliesPage() {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [activeFilter, setActiveFilter] = useState<(typeof filters)[number]>('All');

  const anomaliesQuery = useQuery({
    queryKey: queryKeys.anomalies(100),
    queryFn: () => api.getAnomalies(100),
    refetchInterval: 10_000,
  });

  const anomalies = anomaliesQuery.data ?? [];

  const filteredAnomalies = useMemo(() => {
    return anomalies.filter((anomaly) => activeFilter === 'All' || severity(anomaly.anomaly_score) === activeFilter);
  }, [activeFilter, anomalies]);

  const selectedAnomaly = useMemo<Anomaly | null>(() => {
    if (filteredAnomalies.length === 0) {
      return null;
    }
    return filteredAnomalies.find((anomaly) => anomaly.id === selectedId) ?? filteredAnomalies[0];
  }, [filteredAnomalies, selectedId]);

  const summary = useMemo(() => {
    const total = anomalies.length;
    const critical = anomalies.filter((item) => severity(item.anomaly_score) === 'Critical').length;
    const high = anomalies.filter((item) => severity(item.anomaly_score) === 'High').length;
    const avgScore = total === 0 ? 0 : anomalies.reduce((sum, item) => sum + item.anomaly_score, 0) / total;
    const leakage = anomalies.reduce((sum, item) => sum + Math.max(item.cost_delta ?? 0, 0), 0);
    return { total, critical, high, avgScore, leakage };
  }, [anomalies]);

  if (anomaliesQuery.isLoading) return <LoadingState />;
  if (anomaliesQuery.error) return <ErrorState message={anomaliesQuery.error.message} />;

  return (
    <div className="space-y-6">
      <div className="grid gap-4 xl:grid-cols-4">
        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Active anomaly feed</CardDescription>
            <CardTitle className="flex items-center gap-2 text-3xl">
              <AlertTriangle className="h-7 w-7 text-rose-300" />
              {summary.total}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-slate-400">Hybrid incidents surfaced across unsupervised drift and predicted cost deltas.</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Critical incidents</CardDescription>
            <CardTitle className="flex items-center gap-2 text-3xl">
              <TrendingUp className="h-7 w-7 text-amber-300" />
              {summary.critical + summary.high}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-slate-400">Incidents with elevated blast radius that deserve an operator drill-down now.</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Average anomaly score</CardDescription>
            <CardTitle className="flex items-center gap-2 text-3xl">
              <BrainCircuit className="h-7 w-7 text-cyan-300" />
              {summary.avgScore.toFixed(2)}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-slate-400">Composite score from XGBoost residual magnitude, Isolation Forest drift, and guardrail rules.</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Estimated leakage</CardDescription>
            <CardTitle className="flex items-center gap-2 text-3xl">
              <Sparkles className="h-7 w-7 text-emerald-300" />
              ${summary.leakage.toFixed(2)}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-slate-400">Positive cost delta summed across the current anomaly set.</CardContent>
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
        <Card>
          <CardHeader className="flex flex-col gap-4 border-b border-white/5 pb-4 md:flex-row md:items-center md:justify-between">
            <div>
              <CardTitle>Explainable anomaly stream</CardTitle>
              <CardDescription>Live polling every 10 seconds with enterprise-grade drill-down and severity triage.</CardDescription>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {filters.map((filter) => (
                <Button
                  key={filter}
                  variant={activeFilter === filter ? 'default' : 'ghost'}
                  className="h-9 rounded-full px-3"
                  onClick={() => setActiveFilter(filter)}
                >
                  {filter}
                </Button>
              ))}
              <Button variant="outline" className="gap-2" onClick={() => void anomaliesQuery.refetch()}>
                <RefreshCw className={cn('h-4 w-4', anomaliesQuery.isFetching && 'animate-spin')} />
                Refresh
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-3 pt-6">
            {filteredAnomalies.length === 0 ? (
              <div className="rounded-3xl border border-dashed border-white/10 px-6 py-12 text-center text-sm text-slate-400">
                No anomalies matched the selected severity filter.
              </div>
            ) : (
              filteredAnomalies.map((anomaly) => {
                const isActive = selectedAnomaly?.id === anomaly.id;
                return (
                  <button
                    key={anomaly.id}
                    className={cn(
                      'w-full rounded-3xl border p-5 text-left transition',
                      isActive
                        ? 'border-cyan-400/40 bg-cyan-400/5 shadow-[0_0_0_1px_rgba(34,211,238,0.16)]'
                        : 'border-white/8 bg-white/[0.02] hover:border-white/15 hover:bg-white/[0.04]',
                    )}
                    onClick={() => setSelectedId(anomaly.id)}
                  >
                    <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
                      <div className="space-y-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant={severityVariant(anomaly.anomaly_score)}>{severity(anomaly.anomaly_score)}</Badge>
                          <Badge variant="default">{anomaly.detection_source}</Badge>
                          <Badge variant="info">{anomaly.resource_type ?? 'resource'}</Badge>
                        </div>
                        <div>
                          <div className="text-base font-semibold text-white">{anomaly.resource_name ?? `Resource #${anomaly.resource_id}`}</div>
                          <div className="mt-1 text-sm text-slate-400">{anomaly.reason}</div>
                        </div>
                      </div>
                      <div className="grid gap-2 text-sm text-slate-300 md:text-right">
                        <div>
                          <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Observed / Expected</div>
                          <div className="font-medium text-white">
                            ${anomaly.actual_cost?.toFixed(2) ?? '0.00'} / ${anomaly.expected_cost?.toFixed(2) ?? '0.00'}
                          </div>
                        </div>
                        <div>
                          <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Delta</div>
                          <div className="font-medium text-rose-300">${(anomaly.cost_delta ?? 0).toFixed(2)}</div>
                        </div>
                        <div className="text-xs text-slate-500">{new Date(anomaly.timestamp).toLocaleString()}</div>
                      </div>
                    </div>
                  </button>
                );
              })
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b border-white/5 pb-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <CardTitle>{selectedAnomaly?.resource_name ?? 'Anomaly detail'}</CardTitle>
                <CardDescription>
                  Root-cause explainer for cost deviation, drift score, and feature-level drivers.
                </CardDescription>
              </div>
              {selectedAnomaly ? <Badge variant={severityVariant(selectedAnomaly.anomaly_score)}>{severity(selectedAnomaly.anomaly_score)}</Badge> : null}
            </div>
          </CardHeader>
          <CardContent className="space-y-6 pt-6">
            {!selectedAnomaly ? (
              <div className="rounded-3xl border border-dashed border-white/10 px-6 py-10 text-center text-sm text-slate-400">
                Select an anomaly to inspect its explainability payload.
              </div>
            ) : (
              <>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="rounded-2xl border border-white/8 bg-white/[0.03] p-4">
                    <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Resource context</div>
                    <div className="mt-3 space-y-2 text-sm text-slate-300">
                      <div className="flex items-center gap-2"><Cloud className="h-4 w-4 text-cyan-300" /> {selectedAnomaly.region ?? 'n/a'}</div>
                      <div>Instance type: <span className="text-white">{selectedAnomaly.instance_type ?? 'n/a'}</span></div>
                      <div>Detector: <span className="text-white">{selectedAnomaly.detection_source}</span></div>
                    </div>
                  </div>
                  <div className="rounded-2xl border border-white/8 bg-white/[0.03] p-4">
                    <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Cost baseline</div>
                    <div className="mt-3 grid gap-2 text-sm text-slate-300">
                      <div>Observed cost: <span className="text-white">${selectedAnomaly.actual_cost?.toFixed(4) ?? '0.0000'}</span></div>
                      <div>Expected cost: <span className="text-white">${selectedAnomaly.expected_cost?.toFixed(4) ?? '0.0000'}</span></div>
                      <div>Delta: <span className="text-rose-300">${(selectedAnomaly.cost_delta ?? 0).toFixed(4)}</span></div>
                    </div>
                  </div>
                </div>

                <div className="rounded-2xl border border-white/8 bg-white/[0.03] p-4">
                  <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Analyst summary</div>
                  <p className="mt-3 text-sm leading-6 text-slate-300">{selectedAnomaly.reason}</p>
                </div>

                <div className="rounded-2xl border border-white/8 bg-white/[0.03] p-4">
                  <div className="mb-4 flex items-center justify-between gap-3">
                    <div>
                      <div className="text-xs uppercase tracking-[0.2em] text-slate-500">SHAP contribution chart</div>
                      <p className="mt-1 text-sm text-slate-400">Positive bars pushed the predicted anomaly upward; negative bars offset the risk.</p>
                    </div>
                    <BrainCircuit className="h-5 w-5 text-cyan-300" />
                  </div>
                  <SHAPContributionChart data={selectedAnomaly.shap_contributions} />
                </div>

                <div className="rounded-2xl border border-white/8 bg-white/[0.03] p-4">
                  <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Top contributing features</div>
                  <div className="mt-4 space-y-3">
                    {selectedAnomaly.shap_contributions.length === 0 ? (
                      <div className="text-sm text-slate-400">The anomaly has not produced a feature-level explanation payload yet.</div>
                    ) : (
                      selectedAnomaly.shap_contributions.slice(0, 5).map((item) => (
                        <div key={`${selectedAnomaly.id}-${item.feature}`} className="flex items-center justify-between gap-4 rounded-2xl border border-white/6 bg-slate-950/50 px-4 py-3">
                          <div>
                            <div className="text-sm font-medium text-white">{item.feature_label}</div>
                            <div className="text-xs text-slate-500">Observed value: {item.feature_value ?? 'n/a'}</div>
                          </div>
                          <div className={cn('text-sm font-semibold', item.contribution >= 0 ? 'text-cyan-300' : 'text-rose-300')}>
                            {item.contribution >= 0 ? '+' : ''}
                            {item.contribution.toFixed(4)}
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
