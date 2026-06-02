import { type DatasetStatsResponse, type TraceEvent } from "../api/debugApi";

// Moved from App.tsx — only used by DebugTab.
function formatTime(timestamp: string): string {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return timestamp;
  return date.toLocaleTimeString();
}

function EventCard({ event }: { event: TraceEvent }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="font-semibold text-cyan-200">{event.event}</p>
          <p className="text-sm text-zinc-500">
            {event.module} · {formatTime(event.timestamp)}
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className="rounded-full border border-zinc-700 px-2 py-1 text-zinc-300">
            {event.level}
          </span>
          {event.trace_id && (
            <span className="rounded-full border border-zinc-700 px-2 py-1 text-zinc-300">
              {event.trace_id}
            </span>
          )}
        </div>
      </div>
      <pre className="mt-3 max-h-64 overflow-auto rounded-lg bg-black/50 p-3 text-xs text-zinc-300">
        {JSON.stringify(event.payload, null, 2)}
      </pre>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-950 px-4 py-3 text-center">
      <p className="text-2xl font-bold text-cyan-200">{value}</p>
      <p className="mt-1 text-xs text-zinc-500">{label}</p>
    </div>
  );
}

function ProgressBar({ progress }: { progress: number }) {
  const pct = Math.round(progress * 100);
  return (
    <div className="h-2 w-full rounded-full bg-zinc-800">
      <div
        className="h-2 rounded-full bg-cyan-500 transition-all"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function DatasetSection({
  stats,
  loading,
  error,
}: {
  stats: DatasetStatsResponse | null;
  loading: boolean;
  error: string | null;
}) {
  if (loading && !stats) {
    return (
      <div className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
        <h2 className="text-xl font-semibold">Dataset LoRA v1</h2>
        <p className="mt-3 text-sm text-zinc-500">Cargando estadísticas…</p>
      </div>
    );
  }

  if (error && !stats) {
    return (
      <div className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
        <h2 className="text-xl font-semibold">Dataset LoRA v1</h2>
        <p className="mt-3 rounded-xl border border-red-900 bg-red-950/50 p-3 text-red-200">
          {error}
        </p>
      </div>
    );
  }

  if (!stats) return null;

  // Sort targets by déficit (most needed first)
  const sortedTargets = Object.entries(stats.targets).sort(
    ([, a], [, b]) => b.target - b.count - (a.target - a.count),
  );

  const tagEntries = Object.entries(stats.by_tag).sort(([, a], [, b]) => b - a);
  const sourceEntries = Object.entries(stats.by_source).sort(([, a], [, b]) => b - a);

  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold">Dataset LoRA v1</h2>
          <p className="mt-1 text-xs text-zinc-500">
            calculado {new Date(stats.computed_at).toLocaleString()}
            {loading && " · actualizando…"}
          </p>
        </div>
      </div>

      {error && (
        <p className="mt-3 rounded-xl border border-red-900 bg-red-950/50 p-3 text-red-200 text-sm">
          {error}
        </p>
      )}

      {/* Summary cards */}
      <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <StatCard label="Pares totales" value={stats.total_pairs} />
        <StatCard label="Utilizables" value={stats.usable_pairs} />
        <StatCard label="Sin tone_meta" value={stats.missing_tone_meta} />
        <StatCard label="Operacionales" value={stats.operational_pairs} />
        <StatCard label="Inelegibles" value={stats.ineligible_pairs} />
      </div>

      {/* Targets progress */}
      <div className="mt-6">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-zinc-400">
          Targets por bucket
        </h3>
        <div className="mt-3 grid gap-3">
          {sortedTargets.map(([bucket, data]) => (
            <div key={bucket}>
              <div className="flex items-center justify-between text-sm">
                <span className="font-mono text-zinc-200">{bucket}</span>
                <span className="text-zinc-400">
                  {data.count} / {data.target}{" "}
                  <span className="text-zinc-500">({Math.round(data.progress * 100)}%)</span>
                </span>
              </div>
              <div className="mt-1">
                <ProgressBar progress={data.progress} />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Source distribution */}
      {sourceEntries.length > 0 && (
        <div className="mt-6">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-zinc-400">
            Por fuente
          </h3>
          <div className="mt-2 flex flex-wrap gap-2">
            {sourceEntries.map(([src, count]) => (
              <span
                key={src}
                className="rounded-full border border-zinc-700 px-3 py-1 text-xs text-zinc-300"
              >
                {src}: <span className="font-semibold text-cyan-200">{count}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Tags */}
      <div className="mt-6">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-zinc-400">
          Tags detectados
        </h3>
        {tagEntries.length === 0 ? (
          <p className="mt-2 text-sm text-zinc-500">Sin tags detectados todavía.</p>
        ) : (
          <div className="mt-2 flex flex-wrap gap-2">
            {tagEntries.map(([tag, count]) => (
              <span
                key={tag}
                className="rounded-full border border-zinc-700 px-3 py-1 text-xs text-zinc-300"
              >
                {tag}: <span className="font-semibold text-cyan-200">{count}</span>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Recent pairs */}
      {stats.recent_pairs.length > 0 && (
        <div className="mt-6">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-zinc-400">
            Últimos pares utilizables
          </h3>
          <div className="mt-3 grid gap-2">
            {stats.recent_pairs.map((pair, i) => (
              <div
                key={i}
                className="rounded-xl border border-zinc-800 bg-zinc-950 p-3 text-xs"
              >
                <div className="flex flex-wrap gap-2 text-zinc-500">
                  <span>{new Date(pair.created_at).toLocaleString()}</span>
                  <span className="font-mono text-cyan-400">{pair.primary_bucket}</span>
                  <span>{pair.dataset_source}</span>
                  {pair.tags.map((t) => (
                    <span key={t} className="rounded border border-zinc-700 px-1 text-zinc-400">
                      {t}
                    </span>
                  ))}
                </div>
                <p className="mt-2 text-zinc-400">
                  <span className="text-zinc-500">U: </span>{pair.user_text}
                </p>
                <p className="mt-1 text-zinc-300">
                  <span className="text-zinc-500">S: </span>{pair.sity_text}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export type DebugTabProps = {
  lastTraceId: string | null;
  lastTraceEvents: TraceEvent[];
  recentEvents: TraceEvent[];
  debugError: string | null;
  onRefresh: () => void;
  datasetStats: DatasetStatsResponse | null;
  datasetStatsLoading: boolean;
  datasetStatsError: string | null;
};

export function DebugTab({
  lastTraceId,
  lastTraceEvents,
  recentEvents,
  debugError,
  onRefresh,
  datasetStats,
  datasetStatsLoading,
  datasetStatsError,
}: DebugTabProps) {
  return (
    <div className="grid gap-4">
    <section className="grid gap-4 lg:grid-cols-2">
      <div className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold">Última traza</h2>
            <p className="mt-1 text-sm text-zinc-500">
              {lastTraceId ?? "Sin trace_id registrado todavía"}
            </p>
          </div>
          <button
            onClick={onRefresh}
            className="rounded-xl border border-zinc-700 px-4 py-2 text-sm text-zinc-200 hover:bg-zinc-800"
          >
            Refrescar
          </button>
        </div>

        {debugError && (
          <p className="mt-3 rounded-xl border border-red-900 bg-red-950/50 p-3 text-red-200">
            {debugError}
          </p>
        )}

        <div className="mt-5 grid gap-3">
          {lastTraceEvents.length === 0 && (
            <p className="text-zinc-500">No hay eventos para esta traza.</p>
          )}
          {lastTraceEvents.map((event, index) => (
            <EventCard key={`${event.timestamp}-${index}`} event={event} />
          ))}
        </div>
      </div>

      <div className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
        <h2 className="text-xl font-semibold">Eventos recientes</h2>
        <div className="mt-5 grid gap-3">
          {recentEvents.map((event, index) => (
            <EventCard key={`${event.timestamp}-${index}`} event={event} />
          ))}
        </div>
      </div>
    </section>

    <DatasetSection
      stats={datasetStats}
      loading={datasetStatsLoading}
      error={datasetStatsError}
    />
    </div>
  );
}
