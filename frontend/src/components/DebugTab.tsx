import { type TraceEvent } from "../api/debugApi";

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

export type DebugTabProps = {
  lastTraceId: string | null;
  lastTraceEvents: TraceEvent[];
  recentEvents: TraceEvent[];
  debugError: string | null;
  onRefresh: () => void;
};

export function DebugTab({
  lastTraceId,
  lastTraceEvents,
  recentEvents,
  debugError,
  onRefresh,
}: DebugTabProps) {
  return (
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
  );
}
