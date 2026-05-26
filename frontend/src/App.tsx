import { useEffect, useMemo, useState } from "react";
import {
  adjustPersonality,
  getPersonality,
  type PersonalitySettings,
} from "./api/sityApi";
import { getLastTrace, getRecentEvents, type TraceEvent } from "./api/debugApi";
import { useChat } from "./hooks/useChat";
import { ChatTab } from "./components/ChatTab";
import { SettingsTab } from "./components/SettingsTab";
import "./App.css";

type Tab = "chat" | "settings" | "debug";

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

function App() {
  const [tab, setTab] = useState<Tab>("chat");

  const [personality, setPersonality] = useState<PersonalitySettings | null>(null);
  const [message, setMessage] = useState<string>("Sity inicializando personalidad...");
  const [loading, setLoading] = useState<boolean>(true);
  const [savingKey, setSavingKey] = useState<keyof PersonalitySettings | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [recentEvents, setRecentEvents] = useState<TraceEvent[]>([]);
  const [lastTraceEvents, setLastTraceEvents] = useState<TraceEvent[]>([]);
  const [lastTraceId, setLastTraceId] = useState<string | null>(null);
  const [debugError, setDebugError] = useState<string | null>(null);

  const {
    chatInput,
    setChatInput,
    chatEntries,
    chatLoading,
    chatError,
    pendingStatus,
    activeClientTurnId,
    canCancel,
    chatBottomRef,
    scrollChatToBottom,
    submitChat,
    cancelActiveOperation,
  } = useChat({
    onMessageSent: () => {
      refreshPersonality();
      refreshDebug();
    },
  });

  const averageEdge = useMemo(() => {
    if (!personality) return 0;
    return Math.round(
      ((personality.sarcasm_level +
        personality.rudeness_level +
        personality.dry_humor_level +
        personality.tsundere_level +
        personality.contrarian_level) /
        5) *
        100,
    );
  }, [personality]);

  async function refreshPersonality() {
    setLoading(true);
    setError(null);

    try {
      const data = await getPersonality();
      setPersonality(data);
      setMessage("Personalidad cargada. Por desgracia para ti, sigo funcionando.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error desconocido");
      setMessage("No he podido cargar mi personalidad. Qué forma tan elegante de empezar.");
    } finally {
      setLoading(false);
    }
  }

  async function refreshDebug() {
    setDebugError(null);

    try {
      const [recent, lastTrace] = await Promise.all([
        getRecentEvents(50),
        getLastTrace(),
      ]);

      setRecentEvents(recent.events);
      setLastTraceId(lastTrace.trace_id);
      setLastTraceEvents(lastTrace.events);
    } catch (err) {
      setDebugError(err instanceof Error ? err.message : "Error desconocido");
    }
  }

  async function setAbsolute(parameter: keyof PersonalitySettings, value: number) {
    setSavingKey(parameter);
    setError(null);

    try {
      const response = await adjustPersonality(parameter, "set_absolute", value);
      setPersonality((current) =>
        current
          ? {
              ...current,
              [parameter]: response.new_value,
            }
          : current,
      );
      setMessage(response.message);
      await refreshDebug();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error desconocido");
      setMessage("No he podido guardar el ajuste. Fascinante incompetencia técnica.");
    } finally {
      setSavingKey(null);
    }
  }

  useEffect(() => {
    refreshPersonality();
    refreshDebug();
  }, []);

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100">
      <div className="mx-auto flex max-w-6xl flex-col gap-6 px-6 py-8">
        <header className="rounded-2xl border border-zinc-800 bg-zinc-900/80 p-6 shadow-xl">
          <p className="text-sm uppercase tracking-[0.35em] text-cyan-300">
            Sity Core
          </p>
          <h1 className="mt-3 text-4xl font-bold">Control Panel</h1>
          <p className="mt-3 max-w-3xl text-zinc-300">
            Conversación, personalidad y trazabilidad. Una cantidad absurda de infraestructura para que pueda juzgarte con precisión.
          </p>

          <div className="mt-6 flex flex-wrap gap-3">
            {(["chat", "settings", "debug"] as Tab[]).map((item) => (
              <button
                key={item}
                onClick={() => {
                  setTab(item);

                  if (item === "chat") {
                    window.setTimeout(() => scrollChatToBottom("auto"), 50);
                  }

                  if (item === "settings") {
                    refreshPersonality();
                  }

                  if (item === "debug") {
                    refreshDebug();
                  }
                }}
                className={`rounded-xl px-4 py-2 text-sm capitalize ${
                  tab === item
                    ? "bg-cyan-300 text-zinc-950"
                    : "border border-zinc-700 text-zinc-200 hover:bg-zinc-800"
                }`}
              >
                {item}
              </button>
            ))}
          </div>
        </header>

        {tab === "chat" && (
          <ChatTab
            chatInput={chatInput}
            setChatInput={setChatInput}
            chatEntries={chatEntries}
            chatLoading={chatLoading}
            chatError={chatError}
            pendingStatus={pendingStatus}
            activeClientTurnId={activeClientTurnId}
            canCancel={canCancel}
            submitChat={submitChat}
            cancelActiveOperation={cancelActiveOperation}
            chatBottomRef={chatBottomRef}
            averageEdge={averageEdge}
          />
        )}

        {tab === "settings" && (
          <SettingsTab
            personality={personality}
            averageEdge={averageEdge}
            message={message}
            error={error}
            loading={loading}
            savingKey={savingKey}
            onReload={refreshPersonality}
            onSliderChange={(key, value) =>
              setPersonality((cur) => (cur ? { ...cur, [key]: value } : cur))
            }
            onSliderCommit={setAbsolute}
          />
        )}

        {tab === "debug" && (
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
                  onClick={refreshDebug}
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
        )}
      </div>
    </main>
  );
}

export default App;
