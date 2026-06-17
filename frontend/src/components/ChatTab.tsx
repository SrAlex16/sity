import type React from "react";
import { useRef, useEffect } from "react";

const _MONTHS_ES = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"];

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterdayStart = new Date(todayStart.getTime() - 86_400_000);
  const hhmm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  if (d >= todayStart) return hhmm;
  if (d >= yesterdayStart) return `Ayer ${hhmm}`;
  return `${d.getDate()} ${_MONTHS_ES[d.getMonth()]} ${hhmm}`;
}
import { type ChatEntry } from "../hooks/useChat";
import { API_BASE } from "../api/chatApi";
import { type VoiceSettings } from "../api/voiceApi";

export type ChatTabProps = {
  chatInput: string;
  setChatInput: (value: string) => void;
  chatEntries: ChatEntry[];
  chatLoading: boolean;
  chatError: string | null;
  pendingStatus: string | null;
  activeClientTurnId: string | null;
  canCancel: boolean;
  submitChat: () => Promise<void>;
  cancelActiveOperation: () => Promise<void>;
  chatBottomRef: React.RefObject<HTMLDivElement | null>;
  averageEdge: number;
  isRecording: boolean;
  isTranscribing: boolean;
  recordingError: string | null;
  onToggleRecording: () => void;
  voiceSettings: VoiceSettings | null;
};

export function ChatTab({
  chatInput,
  setChatInput,
  chatEntries,
  chatLoading,
  chatError,
  pendingStatus,
  activeClientTurnId,
  canCancel,
  submitChat,
  cancelActiveOperation,
  chatBottomRef,
  averageEdge,
  isRecording,
  isTranscribing,
  recordingError,
  onToggleRecording,
  voiceSettings,
}: ChatTabProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [chatInput]);

  return (
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
        {chatEntries.map((entry, index) => {
          const hasAudio = (entry.artifacts ?? []).some((a) => a.type === "audio");
          const hideText =
            entry.role === "sity" &&
            hasAudio &&
            voiceSettings?.voice_include_text === false;
          return (
          <div
            key={index}
            className={`max-w-[85%] rounded-2xl p-4 ${
              entry.role === "user"
                ? "ml-auto bg-cyan-300 text-zinc-950"
                : "mr-auto border border-zinc-800 bg-zinc-900 text-zinc-100"
            }`}
          >
            {!hideText && <p className="whitespace-pre-wrap">{entry.text}</p>}
            {entry.artifacts && entry.artifacts.length > 0 && (
              <div className="mt-3 space-y-3">
                {entry.artifacts.map((artifact) => {
                  const url = artifact.url.startsWith("http")
                    ? artifact.url
                    : `${API_BASE}${artifact.url}`;
                  if (artifact.type === "image") {
                    return (
                      <div key={artifact.url} className="space-y-2">
                        <img
                          src={url}
                          alt={artifact.filename}
                          className="max-w-full rounded-xl border border-slate-700"
                        />
                        <a
                          href={url}
                          download={artifact.filename}
                          className="block text-sm underline opacity-70"
                        >
                          Descargar imagen
                        </a>
                      </div>
                    );
                  }
                  if (artifact.type === "audio") {
                    return (
                      <div key={artifact.url} className="space-y-2">
                        <audio controls src={url} className="w-full" />
                        <a
                          href={url}
                          download={artifact.filename}
                          className="block text-sm underline opacity-70"
                        >
                          Descargar audio
                        </a>
                      </div>
                    );
                  }
                  return (
                    <a
                      key={artifact.url}
                      href={url}
                      download={artifact.filename}
                      className="block text-sm underline opacity-70"
                    >
                      Descargar archivo
                    </a>
                  );
                })}
              </div>
            )}
            {entry.meta && (
              <div className="mt-3 rounded-xl bg-black/30 p-3 text-xs text-zinc-400">
                <p>
                  {entry.meta.provider} · {entry.meta.model} · trace{" "}
                  {entry.meta.trace_id}
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
            {entry.created_at && (
              <p className={`mt-1 text-xs ${entry.role === "user" ? "text-right text-zinc-600" : "text-zinc-500"}`}>
                {formatTimestamp(entry.created_at)}
              </p>
            )}
          </div>
          );
        })}
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

      {recordingError && (
        <p className="mt-3 rounded-xl border border-red-900 bg-red-950/50 p-3 text-red-200">
          {recordingError}
        </p>
      )}

      <div className="mt-4 flex items-end gap-3">
        <textarea
          ref={textareaRef}
          rows={1}
          value={chatInput}
          onChange={(event) => setChatInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              submitChat();
            }
          }}
          placeholder={isRecording ? "Grabando…" : isTranscribing ? "Transcribiendo…" : "Habla con Sity..."}
          className="min-w-0 flex-1 resize-none overflow-y-auto rounded-xl border border-zinc-700 bg-zinc-950 px-4 py-3 text-zinc-100 outline-none focus:border-cyan-300"
          style={{ maxHeight: "12rem" }}
        />
        <button
          type="button"
          onClick={onToggleRecording}
          disabled={isTranscribing || chatLoading}
          title={isRecording ? "Detener grabación" : "Grabar audio"}
          className={`rounded-xl px-4 py-3 font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
            isRecording
              ? "bg-red-500 text-white hover:bg-red-600"
              : "border border-zinc-700 text-zinc-300 hover:bg-zinc-800"
          }`}
        >
          {isTranscribing ? (
            "…"
          ) : isRecording ? (
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-5 w-5">
              <rect x="6" y="6" width="12" height="12" rx="2" />
            </svg>
          ) : (
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-5 w-5">
              <path d="M12 1a4 4 0 0 1 4 4v7a4 4 0 0 1-8 0V5a4 4 0 0 1 4-4Zm0 2a2 2 0 0 0-2 2v7a2 2 0 1 0 4 0V5a2 2 0 0 0-2-2Zm-7 9a1 1 0 0 1 1 1 6 6 0 0 0 12 0 1 1 0 1 1 2 0 8 8 0 0 1-7 7.938V22h2a1 1 0 1 1 0 2H9a1 1 0 1 1 0-2h2v-2.062A8 8 0 0 1 4 13a1 1 0 0 1 1-1Z" />
            </svg>
          )}
        </button>
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
  );
}
