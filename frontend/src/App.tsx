import { useEffect, useMemo, useState } from "react";
import {
  adjustPersonality,
  getPersonality,
  resetPersonality,
  type PersonalitySettings,
} from "./api/sityApi";
import {
  disableDatasetCapture,
  fetchDatasetCapture,
  fetchDatasetStats,
  getLastTrace,
  getRecentEvents,
  updateDatasetCapture,
  type DatasetCaptureContext,
  type DatasetCaptureRequest,
  type DatasetStatsResponse,
  type TraceEvent,
} from "./api/debugApi";
import { useChat } from "./hooks/useChat";
import { useVoiceInput } from "./hooks/useVoiceInput";
import { ChatTab } from "./components/ChatTab";
import { PersonalityTab } from "./components/PersonalityTab";
import { DebugTab } from "./components/DebugTab";
import { DatasetTab } from "./components/DatasetTab";
import { VoiceSettingsTab } from "./components/VoiceSettingsTab";
import {
  getVoiceSettings,
  updateVoiceSettings,
  type VoiceSettings,
} from "./api/voiceApi";
import "./App.css";

type Tab = "chat" | "personality" | "voice" | "debug" | "dataset";

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

  const [datasetStats, setDatasetStats] = useState<DatasetStatsResponse | null>(null);
  const [datasetStatsLoading, setDatasetStatsLoading] = useState(false);
  const [datasetStatsError, setDatasetStatsError] = useState<string | null>(null);

  const [datasetCapture, setDatasetCapture] = useState<DatasetCaptureContext | null>(null);
  const [datasetCaptureLoading, setDatasetCaptureLoading] = useState(false);
  const [datasetCaptureError, setDatasetCaptureError] = useState<string | null>(null);

  const [voiceSettings, setVoiceSettings] = useState<VoiceSettings | null>(null);
  const [voiceLoading, setVoiceLoading] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);

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
    setVoiceTranscript,
  } = useChat({
    onMessageSent: () => {
      refreshPersonality();
      refreshTrace();
    },
  });

  const { isRecording, isTranscribing, recordingError, toggleRecording } = useVoiceInput({
    onTranscript: setVoiceTranscript,
  });

  const averageEdge = useMemo(() => {
    if (!personality) return 0;
    return Math.round(
      ((personality.sarcasm_level +
        personality.rudeness_level +
        personality.dry_humor_level +
        personality.frialdad_afectiva_level +
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

  async function restorePersonalityToDefaults() {
    setLoading(true);
    setError(null);
    try {
      const data = await resetPersonality();
      setPersonality(data);
      setMessage("Valores canónicos restaurados. Sigues siendo igual de impredecible.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error desconocido");
      setMessage("No he podido restaurar los valores. Para variar.");
    } finally {
      setLoading(false);
    }
  }

  async function refreshTrace() {
    setDebugError(null);
    try {
      const [recent, lastTrace] = await Promise.all([getRecentEvents(50), getLastTrace()]);
      setRecentEvents(recent.events);
      setLastTraceId(lastTrace.trace_id);
      setLastTraceEvents(lastTrace.events);
    } catch (err) {
      setDebugError(err instanceof Error ? err.message : "Error desconocido");
    }
  }

  async function refreshDataset() {
    setDatasetStatsError(null);
    setDatasetStatsLoading(true);
    setDatasetCaptureError(null);
    setDatasetCaptureLoading(true);

    const [statsSettled, captureSettled] = await Promise.allSettled([
      fetchDatasetStats(),
      fetchDatasetCapture(),
    ]);

    if (statsSettled.status === "fulfilled") {
      setDatasetStats(statsSettled.value);
    } else {
      const err = statsSettled.reason;
      setDatasetStatsError(err instanceof Error ? err.message : "Error cargando stats");
    }

    if (captureSettled.status === "fulfilled") {
      setDatasetCapture(captureSettled.value);
    } else {
      const err = captureSettled.reason;
      setDatasetCaptureError(err instanceof Error ? err.message : "Error cargando captura");
    }

    setDatasetStatsLoading(false);
    setDatasetCaptureLoading(false);
  }

  async function saveDatasetCapture(payload: DatasetCaptureRequest): Promise<void> {
    setDatasetCaptureLoading(true);
    setDatasetCaptureError(null);
    try {
      const result = await updateDatasetCapture(payload);
      setDatasetCapture(result);
    } catch (err) {
      setDatasetCaptureError(err instanceof Error ? err.message : "Error guardando");
    } finally {
      setDatasetCaptureLoading(false);
    }
  }

  async function refreshVoiceSettings() {
    setVoiceLoading(true);
    setVoiceError(null);
    try {
      setVoiceSettings(await getVoiceSettings());
    } catch (err) {
      setVoiceError(err instanceof Error ? err.message : "Error desconocido");
    } finally {
      setVoiceLoading(false);
    }
  }

  async function saveVoiceSettings(next: VoiceSettings) {
    setVoiceLoading(true);
    setVoiceError(null);
    try {
      setVoiceSettings(await updateVoiceSettings(next));
    } catch (err) {
      setVoiceError(err instanceof Error ? err.message : "Error guardando");
    } finally {
      setVoiceLoading(false);
    }
  }

  async function disableDatasetCaptureAsync(): Promise<void> {
    setDatasetCaptureLoading(true);
    setDatasetCaptureError(null);
    try {
      const result = await disableDatasetCapture();
      setDatasetCapture(result);
    } catch (err) {
      setDatasetCaptureError(err instanceof Error ? err.message : "Error desactivando");
    } finally {
      setDatasetCaptureLoading(false);
    }
  }

  async function setAbsolute(parameter: keyof PersonalitySettings, value: number) {
    setSavingKey(parameter);
    setError(null);
    try {
      const response = await adjustPersonality(parameter, "set_absolute", value);
      setPersonality((current) =>
        current ? { ...current, [parameter]: response.new_value } : current,
      );
      setMessage(response.message);
      await refreshTrace();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error desconocido");
      setMessage("No he podido guardar el ajuste. Fascinante incompetencia técnica.");
    } finally {
      setSavingKey(null);
    }
  }

  useEffect(() => {
    refreshPersonality();
    refreshTrace();
    refreshDataset();
    refreshVoiceSettings();
  }, []);

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100">
      <div className="mx-auto flex max-w-6xl flex-col gap-6 px-6 py-8">
        <header className="rounded-2xl border border-zinc-800 bg-zinc-900/80 p-6 shadow-xl">
          <div className="flex items-center gap-3">
            <p className="text-sm uppercase tracking-[0.35em] text-cyan-300">Sity Core</p>
            {datasetCapture?.enabled && (
              <span className="rounded-full border border-amber-500 bg-amber-950/60 px-2 py-0.5 text-xs text-amber-300">
                Dataset capture: {datasetCapture.dataset_source}
                {datasetCapture.speaker_label ? ` / ${datasetCapture.speaker_label}` : ""}
              </span>
            )}
          </div>
          <h1 className="mt-3 text-4xl font-bold">Control Panel</h1>
          <p className="mt-3 max-w-3xl text-zinc-300">
            Conversación, personalidad y trazabilidad. Una cantidad absurda de infraestructura para que pueda juzgarte con precisión.
          </p>

          <div className="mt-6 flex flex-wrap gap-3">
            {(["chat", "personality", "voice", "debug", "dataset"] as Tab[]).map((item) => (
              <button
                key={item}
                onClick={() => {
                  setTab(item);
                  if (item === "chat") window.setTimeout(() => scrollChatToBottom("auto"), 50);
                  if (item === "personality") refreshPersonality();
                  if (item === "voice") refreshVoiceSettings();
                  if (item === "debug") refreshTrace();
                  if (item === "dataset") refreshDataset();
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
            isRecording={isRecording}
            isTranscribing={isTranscribing}
            recordingError={recordingError}
            onToggleRecording={toggleRecording}
          />
        )}

        {tab === "personality" && (
          <PersonalityTab
            personality={personality}
            averageEdge={averageEdge}
            message={message}
            error={error}
            loading={loading}
            savingKey={savingKey}
            onReload={refreshPersonality}
            onRestoreDefaults={restorePersonalityToDefaults}
            onSliderChange={(key, value) =>
              setPersonality((cur) => (cur ? { ...cur, [key]: value } : cur))
            }
            onSliderCommit={setAbsolute}
          />
        )}

        {tab === "voice" && (
          <VoiceSettingsTab
            settings={voiceSettings}
            loading={voiceLoading}
            error={voiceError}
            onReload={refreshVoiceSettings}
            onChange={saveVoiceSettings}
          />
        )}

        {tab === "debug" && (
          <DebugTab
            lastTraceId={lastTraceId}
            lastTraceEvents={lastTraceEvents}
            recentEvents={recentEvents}
            debugError={debugError}
            onRefresh={refreshTrace}
          />
        )}

        {tab === "dataset" && (
          <DatasetTab
            datasetStats={datasetStats}
            datasetStatsLoading={datasetStatsLoading}
            datasetStatsError={datasetStatsError}
            datasetCapture={datasetCapture}
            datasetCaptureLoading={datasetCaptureLoading}
            datasetCaptureError={datasetCaptureError}
            onSaveDatasetCapture={saveDatasetCapture}
            onDisableDatasetCapture={disableDatasetCaptureAsync}
            onRestorePersonality={restorePersonalityToDefaults}
            onRefresh={refreshDataset}
          />
        )}
      </div>
    </main>
  );
}

export default App;
