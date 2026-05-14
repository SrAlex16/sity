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
