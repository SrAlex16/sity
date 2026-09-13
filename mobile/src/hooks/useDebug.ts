import { useState, useCallback } from 'react';

export interface TraceEvent {
  timestamp: string;
  level: string;
  module: string;
  event: string;
  trace_id: string | null;
  session_id: string | null;
  turn_id: string | null;
  payload: Record<string, unknown>;
}

export interface RecentPair {
  user_text: string;
  sity_text: string;
  primary_bucket: string;
  tags: string[];
  dataset_source: string;
  created_at: string;
}

export interface BucketTarget {
  count: number;
  target: number;
  progress: number;
}

export interface DatasetStats {
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
}

export function useDebug() {
  const [recentEvents, setRecentEvents] = useState<TraceEvent[]>([]);
  const [lastTraceId, setLastTraceId] = useState<string | null>(null);
  const [lastTraceEvents, setLastTraceEvents] = useState<TraceEvent[]>([]);
  const [datasetStats, setDatasetStats] = useState<DatasetStats | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadTrace = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [eventsRes, traceRes, statsRes] = await Promise.all([
        fetch('/debug/events/recent?limit=50'),
        fetch('/debug/last-trace'),
        fetch('/debug/dataset-stats'),
      ]);
      if (eventsRes.ok) {
        const d = await eventsRes.json() as { events: TraceEvent[] };
        setRecentEvents(d.events ?? []);
      }
      if (traceRes.ok) {
        const d = await traceRes.json() as { trace_id: string | null; events: TraceEvent[] };
        setLastTraceId(d.trace_id ?? null);
        setLastTraceEvents(d.events ?? []);
      }
      if (statsRes.ok) {
        setDatasetStats(await statsRes.json() as DatasetStats);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error cargando datos de debug');
    } finally {
      setIsLoading(false);
    }
  }, []);

  return { recentEvents, lastTraceId, lastTraceEvents, datasetStats, isLoading, error, reload: loadTrace };
}
