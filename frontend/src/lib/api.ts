import axios from 'axios';
import type {
  Action,
  Anomaly,
  AwsMetric,
  AwsSyncResponse,
  CostSummary,
  Metric,
  ResourceSummary,
} from '../types';

export const apiClient = axios.create({
  baseURL: '/api',
  timeout: 12000,
  headers: {
    'Content-Type': 'application/json',
  },
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const detail = error.response?.data?.detail;
    const message = typeof detail === 'string' ? detail : error.message || 'Request failed';
    return Promise.reject(new Error(message));
  },
);

export const queryKeys = {
  health: ['health'] as const,
  cost: ['cost'] as const,
  resources: ['resources'] as const,
  awsResources: ['aws', 'resources'] as const,
  metrics: (limit = 100) => ['metrics', limit] as const,
  awsMetrics: (limit = 100) => ['aws', 'metrics', limit] as const,
  anomalies: (limit = 100) => ['anomalies', limit] as const,
  actions: (limit = 100) => ['actions', limit] as const,
};

async function get<T>(path: string, params?: Record<string, string | number | boolean | undefined>) {
  const response = await apiClient.get<T>(path, { params });
  return response.data;
}

async function post<T>(path: string, body?: unknown) {
  const response = await apiClient.post<T>(path, body);
  return response.data;
}

export const api = {
  getHealth: () => get<{ status: string; service: string }>('/'),
  getCost: () => get<CostSummary>('/cost'),
  getResources: () => get<ResourceSummary[]>('/resources'),
  getAwsResources: () => get<ResourceSummary[]>('/aws/resources'),
  getMetrics: (limit = 100) => get<Metric[]>('/metrics', { limit }),
  getAwsMetrics: (limit = 100) => get<AwsMetric[]>('/aws/metrics', { limit }),
  syncAws: () => post<AwsSyncResponse>('/aws/sync'),
  getAnomalies: (limit = 100) => get<Anomaly[]>('/anomalies', { limit }),
  getActions: (limit = 100) => get<Action[]>('/actions', { limit }),
  triggerAction: (resourceId: number, actionType: string, dryRun = true) =>
    post<{ action_id: number; status: string; estimated_savings: number }>('/actions', {
      resource_id: resourceId,
      action_type: actionType,
      dry_run: dryRun,
    }),
};
