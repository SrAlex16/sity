import { useEffect, useMemo, useRef, useState } from "react";
import {
  adjustPersonality,
  getPersonality,
  type PersonalitySettings,
} from "./api/sityApi";
import { getLastTrace, getRecentEvents, type TraceEvent } from "./api/debugApi";
import { getCurrentChat, sendChatMessage, type ChatArtifact, type ChatMessageResponse, API_BASE } from "./api/chatApi";
import "./App.css";

const LABELS: Record<keyof PersonalitySettings, string> = {
  sarcasm_level: "Sarcasmo",
  rudeness_level: "Mala leche",
  warmth_level: "Calidez",
  honesty_level: "Honestidad",
  initiative_level: "Iniciativa",
    dry_humor_level: "Humor seco",
  melancholy_level: "Melancolía",
  tsundere_level: "Modo tsundere",
  contrarian_level: "Contradicción",
  patience_level: "Paciencia",
  refusal_chance: "Probabilidad de negarse",
  helpfulness_level: "Nivel de ayuda",
  verbosity_level: "Verbosidad",
};

const ORDER: Array<keyof PersonalitySettings> = [
  "sarcasm_level",
  "rudeness_level",
  "warmth_level",
  "honesty_level",
  "initiative_level",
  "dry_humor_level",
  "melancholy_level",
  "tsundere_level",
  "contrarian_level",
  "patience_level",
  "refusal_chance",
  "helpfulness_level",
  "verbosity_level",
];

type Tab = "chat" | "settings" | "debug";

type ChatEntry = {
  role: "user" | "sity";
  text: string;
  meta?: ChatMessageResponse;
  artifacts?: ChatArtifact[];
};

function percent(value: number): number {
  return Math.round(value * 100);
}

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

function createClientTurnId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `turn_${Date.now()}_${Math.random().toString(16).slice(2)}`;
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

  const [chatInput, setChatInput] = useState("");
  const [chatEntries, setChatEntries] = useState<ChatEntry[]>([
    {
      role: "sity",
      text: "Estoy despierta. No prometo que eso mejore tus decisiones.",
    },
  ]);
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [pendingStatus, setPendingStatus] = useState<string | null>(null);
  const [activeClientTurnId, setActiveClientTurnId] = useState<string | null>(null);
  const [canCancel, setCanCancel] = useState(false);
  const chatBottomRef = useRef<HTMLDivElement | null>(null);

  function scrollChatToBottom(behavior: ScrollBehavior = "smooth") {
    window.setTimeout(() => {
      chatBottomRef.current?.scrollIntoView({ behavior });
    }, 0);
  }

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

  async function loadCurrentChat() {
    try {
      const response = await getCurrentChat();

      if (response.messages.length > 0) {
        setChatEntries(
          response.messages.map((message) => ({
            role: message.role as "user" | "sity",
            text: message.text,
          })),
        );
        window.setTimeout(() => scrollChatToBottom("auto"), 50);
      }
    } catch {
      // Keep local default greeting if loading fails.
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

  async function cancelActiveOperation() {
    if (!activeClientTurnId) return;
    setCanCancel(false);
    setPendingStatus("Cancelando…");
    await fetch(`${API_BASE}/events/chat/${activeClientTurnId}/cancel`, { method: "POST" });
  }

  async function submitChat() {
    console.log("[Sity submit] called", { chatInput, chatLoading });

    const trimmed = chatInput.trim();

    if (!trimmed || chatLoading) {
      console.log("[Sity submit] blocked", { trimmed, chatLoading });
      return;
    }

    const clientTurnId = createClientTurnId();
    console.log("[Sity submit] clientTurnId", clientTurnId);

    setChatInput("");
    setChatError(null);
    setChatLoading(true);
    setCanCancel(false);
    setPendingStatus("Sity está trabajando…");
    setActiveClientTurnId(clientTurnId);
    setChatEntries((current) => [...current, { role: "user", text: trimmed }]);
    window.setTimeout(() => scrollChatToBottom("smooth"), 50);

    const eventSource = new EventSource(`${API_BASE}/events/chat/${clientTurnId}`);
    console.log("[Sity submit] EventSource opened");

    eventSource.onopen = () => {
      console.log("[Sity SSE] open", clientTurnId);
    };

    eventSource.onmessage = (e) => {
      console.log("[Sity SSE] message raw", e.data);
      const data = JSON.parse(e.data) as {
        type: string;
        label?: string;
        can_cancel?: boolean;
      };
      console.log("[Sity SSE] message parsed", data);
      if (data.type === "tool_started") {
        setPendingStatus(data.label ?? "Trabajando…");
        setCanCancel(Boolean(data.can_cancel));
      }
      if (data.type === "tool_finished") {
        setCanCancel(false);
        setPendingStatus("Procesando respuesta…");
      }
      if (data.type === "cancelled") {
        setPendingStatus(data.label ?? "Cancelado.");
        setCanCancel(false);
      }

      if (data.type === "done" || data.type === "error") {
        setCanCancel(false);
        setActiveClientTurnId(null);
        eventSource.close();
      }
    };

    eventSource.onerror = (error) => {
      console.error("[Sity SSE] error", error);
    };

    try {
      console.log("[Sity submit] sending chat message");
      const response = await sendChatMessage(trimmed, clientTurnId);
      console.log("[Sity submit] response", response);

      setChatEntries((current) => [
        ...current,
        {
          role: "sity",
          text: response.text || "(sin respuesta)",
          meta: response,
          artifacts: response.artifacts ?? [],
        },
      ]);
      window.setTimeout(() => scrollChatToBottom("smooth"), 50);

      refreshPersonality();
      refreshDebug();
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Error desconocido";
      setChatError(errorMessage);
      setChatEntries((current) => [
        ...current,
        {
          role: "sity",
          text: `No he podido responder. ${errorMessage}`,
        },
      ]);
    } finally {
      console.log("[Sity submit] finally cleanup");
      eventSource.close();
      setPendingStatus(null);
      setCanCancel(false);
      setActiveClientTurnId(null);
      setChatLoading(false);
    }
  }

  useEffect(() => {
    refreshPersonality();
    refreshDebug();
    loadCurrentChat();
  }, []);

  useEffect(() => {
    scrollChatToBottom("smooth");
  }, [chatEntries, chatLoading]);

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
          <section className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
            <div className="flex items-center justify-between gap-4">
              <div>
                <h2 className="text-xl font-semibold">Chat</h2>
                <p className="mt-1 text-sm text-zinc-500">
                  Habla con Sity sin tener que leer JSON como un animal.
                </p>
              </div>
              <div className="rounded-xl border border-zinc-700 px-3 py-2 text-sm text-zinc-300">
                Encabronamiento: {averageEdge}%
              </div>
            </div>

            <div className="mt-5 flex max-h-[560px] flex-col gap-4 overflow-auto rounded-2xl bg-zinc-950 p-4">
              {chatEntries.map((entry, index) => (
                <div
                  key={index}
                  className={`max-w-[85%] rounded-2xl p-4 ${
                    entry.role === "user"
                      ? "ml-auto bg-cyan-300 text-zinc-950"
                      : "mr-auto border border-zinc-800 bg-zinc-900 text-zinc-100"
                  }`}
                >
                  <p className="whitespace-pre-wrap">{entry.text}</p>
                  {entry.artifacts && entry.artifacts.length > 0 && (
                    <div className="mt-3 space-y-3">
                      {entry.artifacts.map((artifact) => {
                        const url = artifact.url.startsWith("http") ? artifact.url : `${API_BASE}${artifact.url}`;
                        if (artifact.type === "image") {
                          return (
                            <div key={artifact.url} className="space-y-2">
                              <img src={url} alt={artifact.filename} className="max-w-full rounded-xl border border-slate-700" />
                              <a href={url} download={artifact.filename} className="block text-sm underline opacity-70">
                                Descargar imagen
                              </a>
                            </div>
                          );
                        }
                        if (artifact.type === "audio") {
                          return (
                            <div key={artifact.url} className="space-y-2">
                              <audio controls src={url} className="w-full" />
                              <a href={url} download={artifact.filename} className="block text-sm underline opacity-70">
                                Descargar audio
                              </a>
                            </div>
                          );
                        }
                        return (
                          <a key={artifact.url} href={url} download={artifact.filename} className="block text-sm underline opacity-70">
                            Descargar archivo
                          </a>
                        );
                      })}
                    </div>
                  )}
                  {entry.meta && (
                    <div className="mt-3 rounded-xl bg-black/30 p-3 text-xs text-zinc-400">
                      <p>
                        {entry.meta.provider} · {entry.meta.model} · trace {entry.meta.trace_id}
                      </p>
                      <p>
                        tokens: {entry.meta.usage.input_tokens} in /{" "}
                        {entry.meta.usage.output_tokens} out · diario:{" "}
                        {Math.round(entry.meta.usage.daily_ratio * 100)}%
                      </p>
                      {entry.meta.warnings.map((warning, warningIndex) => (
                        <p key={warningIndex} className="mt-1 text-yellow-300">
                          {warning}
                        </p>
                      ))}
                    </div>
                  )}
                </div>
              ))}
              {chatLoading && (
                <div className="mr-auto rounded-2xl border border-zinc-800 bg-zinc-900 p-4 text-zinc-400">
                  {pendingStatus ?? "Pensando…"}
                </div>
              )}
              <div ref={chatBottomRef} />
            </div>

            {chatError && (
              <p className="mt-3 rounded-xl border border-red-900 bg-red-950/50 p-3 text-red-200">
                {chatError}
              </p>
            )}

            <div className="mt-4 flex gap-3">
              <input
                value={chatInput}
                onChange={(event) => setChatInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    submitChat();
                  }
                }}
                placeholder="Habla con Sity..."
                className="min-w-0 flex-1 rounded-xl border border-zinc-700 bg-zinc-950 px-4 py-3 text-zinc-100 outline-none focus:border-cyan-300"
              />
              {activeClientTurnId && canCancel ? (
                <button
                  type="button"
                  onClick={cancelActiveOperation}
                  className="rounded-xl bg-red-500 px-5 py-3 font-medium text-white hover:bg-red-600"
                >
                  Cancelar
                </button>
              ) : (
                <button
                  type="button"
                  onClick={submitChat}
                  disabled={chatLoading}
                  className="rounded-xl bg-cyan-300 px-5 py-3 font-medium text-zinc-950 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Enviar
                </button>
              )}
            </div>
          </section>
        )}

        {tab === "settings" && (
          <>
            <section className="grid gap-4 md:grid-cols-[1fr_280px]">
              <div className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
                <h2 className="text-xl font-semibold">Respuesta de Sity</h2>
                <p className="mt-3 rounded-xl bg-zinc-950 p-4 text-cyan-100">
                  {message}
                </p>
                {error && (
                  <p className="mt-3 rounded-xl border border-red-900 bg-red-950/50 p-3 text-red-200">
                    {error}
                  </p>
                )}
              </div>

              <div className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
                <h2 className="text-xl font-semibold">Encabronamiento</h2>
                <p className="mt-4 text-5xl font-bold text-cyan-300">{averageEdge}%</p>
                <p className="mt-2 text-sm text-zinc-400">
                  Media de sarcasmo, mala leche, humor seco, tsundere y contradicción. Métrica científicamente dudosa, como casi todo lo divertido.
                </p>
              </div>
            </section>

            <section className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
              <div className="flex items-center justify-between gap-4">
                <h2 className="text-xl font-semibold">Parámetros</h2>
                <button
                  onClick={refreshPersonality}
                  className="rounded-xl border border-zinc-700 px-4 py-2 text-sm text-zinc-200 hover:bg-zinc-800"
                >
                  Recargar
                </button>
              </div>

              {loading && <p className="mt-4 text-zinc-400">Cargando...</p>}

              {personality && (
                <div className="mt-6 grid gap-5">
                  {ORDER.map((key) => (
                    <div key={key} className="rounded-xl bg-zinc-950 p-4">
                      <div className="mb-3 flex items-center justify-between gap-4">
                        <div>
                          <p className="font-medium">{LABELS[key]}</p>
                          <p className="text-sm text-zinc-500">{key}</p>
                        </div>
                        <div className="text-right">
                          <p className="text-2xl font-bold text-cyan-300">
                            {percent(personality[key])}%
                          </p>
                          {savingKey === key && (
                            <p className="text-xs text-zinc-500">guardando...</p>
                          )}
                        </div>
                      </div>

                      <input
                        type="range"
                        min="0"
                        max="100"
                        value={percent(personality[key])}
                        onChange={(event) => {
                          const value = Number(event.target.value) / 100;
                          setPersonality((current) =>
                            current
                              ? {
                                  ...current,
                                  [key]: value,
                                }
                              : current,
                          );
                        }}
                        onMouseUp={(event) => {
                          const value = Number(
                            (event.target as HTMLInputElement).value,
                          ) / 100;
                          setAbsolute(key, value);
                        }}
                        onTouchEnd={(event) => {
                          const value = Number(
                            (event.target as HTMLInputElement).value,
                          ) / 100;
                          setAbsolute(key, value);
                        }}
                        className="w-full"
                      />
                    </div>
                  ))}
                </div>
              )}
            </section>
          </>
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
