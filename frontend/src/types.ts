export type CostTrendPoint = {
  timestamp: string;
  estimated_cost: number;
};

export type ResourceSummary = {
  id: number;
  name: string;
  type: 'ec2' | 'lambda' | 's3';
  region: string;
  status: string;
  provider: string;
  external_id: string | null;
  instance_type: string | null;
  cloud_state: string | null;
  tags: Record<string, string>;
  created_at: string;
  latest_cost: number | null;
  cost_per_hour: number | null;
  latest_cpu: number | null;
  latest_memory: number | null;
  latest_requests: number | null;
  latest_network_in: number | null;
  latest_network_out: number | null;
};

export type CostSummary = {
  total_cost: number;
  total_savings: number;
  projected_monthly_cost: number;
  trend: CostTrendPoint[];
  per_resource: Array<{
    resource_id: number;
    resource_name: string;
    resource_type: string;
    total_cost: number;
  }>;
};

export type Metric = {
  id: number;
  resource_id: number;
  timestamp: string;
  cpu_usage: number;
  memory_usage: number;
  requests: number;
  storage_used: number;
  network_in: number;
  network_out: number;
};

export type AwsMetric = {
  resource_id: number;
  instance_id: string | null;
  instance_type: string | null;
  timestamp: string;
  cpu_usage: number;
  network_in: number;
  network_out: number;
};

export type AwsSyncResponse = {
  resources_synced: number;
  metrics_ingested: number;
  cost_records_created: number;
  anomalies_detected: number;
  actions_triggered: number;
};

export type SHAPContribution = {
  feature: string;
  feature_label: string;
  feature_value: string | number | null;
  contribution: number;
  direction: string;
  impact_rank: number;
  metadata: Record<string, unknown>;
};

export type Anomaly = {
  id: number;
  resource_id: number;
  resource_name: string | null;
  resource_type: string | null;
  region: string | null;
  instance_type: string | null;
  timestamp: string;
  anomaly_score: number;
  reason: string;
  detection_source: string;
  expected_cost: number | null;
  actual_cost: number | null;
  cost_delta: number | null;
  shap_contributions: SHAPContribution[];
};

export type Action = {
  id: number;
  resource_id: number;
  action_type: string;
  timestamp: string;
  estimated_savings: number;
};
