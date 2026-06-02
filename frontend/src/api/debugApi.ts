export type TraceEvent = {
  timestamp: string;
  level: string;
  module: string;
  event: string;
  trace_id: string | null;
  session_id: string | null;
  turn_id: string | null;
  payload: Record<string, unknown>;
};

export type RecentEventsResponse = {
  ok: boolean;
  events: TraceEvent[];
};

export type LastTraceResponse = {
  ok: boolean;
  trace_id: string | null;
  events: TraceEvent[];
};

export type RecentPair = {
  user_text: string;
  sity_text: string;
  primary_bucket: string;
  tags: string[];
  dataset_source: string;
  created_at: string;
};

export type BucketTarget = {
  count: number;
  target: number;
  progress: number;
};

export type DatasetStatsResponse = {
  ok: boolean;
  computed_at: string;
  total_pairs: number;
  usable_pairs: number;
  missing_tone_meta: number;
  ineligible_pairs: number;
  operational_pairs: number;
  by_source: Record<string, number>;
  by_primary_bucket: Record<string, number>;
  by_tag: Record<string, number>;
  targets: Record<string, BucketTarget>;
  recent_pairs: RecentPair[];
};

const API_BASE = import.meta.env.VITE_SITY_API_BASE ?? "http://localhost:8000";

export async function getRecentEvents(limit = 100): Promise<RecentEventsResponse> {
  const response = await fetch(`${API_BASE}/debug/events/recent?limit=${limit}`);

  if (!response.ok) {
    throw new Error(`Failed to load debug events: ${response.status}`);
  }

  return response.json();
}

export async function getLastTrace(): Promise<LastTraceResponse> {
  const response = await fetch(`${API_BASE}/debug/last-trace`);

  if (!response.ok) {
    throw new Error(`Failed to load last trace: ${response.status}`);
  }

  return response.json();
}

export async function fetchDatasetStats(): Promise<DatasetStatsResponse> {
  const response = await fetch(`${API_BASE}/debug/dataset-stats`);

  if (!response.ok) {
    throw new Error(`Failed to load dataset stats: ${response.status}`);
  }

  return response.json();
}
